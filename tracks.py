import os
import sys
import csv
import re
import webbrowser
import urllib.parse

from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QDialog, QLabel, QProgressBar, QMessageBox, QPushButton, QTableView, QFileDialog, QInputDialog, QStyledItemDelegate
from PySide6.QtCore import Qt, QAbstractTableModel, QTimer, QRect, QItemSelection, QItemSelectionModel, QPointF
from PySide6.QtGui import QColor, QAction, QKeySequence, QBrush, QGradient, QLinearGradient, QTransform

STATE_OPTIONS = {
	"Unknown": {"key": "U", "color": "#222"},
	"Missing": {"key": "N", "color": "#622"},
	"Unverified": {"key": "V", "color": "#662"},
	"Incorrect": {"key": "X", "color": "#642"},
	"Unsynced": {"key": "S", "color": "#226"},
	"Complete": {"key": "C", "color": "#262"},
}

LYRIC_SITES = {
	"Musixmatch": {
		"key": "M",
		"url": "https://www.musixmatch.com/search?query={query}"
	},
	"Genius": {
		"key": "G",
		"url": "https://genius.com/search?q={query}"
	}
}

HEADERS = ["Name", "Artist", *LYRIC_SITES.keys(), "Instrumental"]

def load_library(fp):
	import plistlib
	with open(fp or "./Library.xml", 'rb') as f:
		library = plistlib.load(f)

	data = []

	for song in library['Tracks'].values():
		data.append({
			"Name": song.get('Name'),
			"Artist": song.get('Artist'),
			**{site: "Unknown" for site in LYRIC_SITES.keys()},
			"Instrumental": False
		})

	return data

# https://stackoverflow.com/a/79131764
class GradientDelegate(QStyledItemDelegate):
	def initStyleOption(self, opt, index):
		super().initStyleOption(opt, index)
		if (
			isinstance(opt.backgroundBrush, QBrush) 
			and opt.backgroundBrush.gradient()
			and (opt.rect.x() or opt.rect.y())
		):
			grad = opt.backgroundBrush.gradient()
			grad.setStart(QPointF())
			grad.setFinalStop(QPointF(0, opt.rect.height()))

class TrackTableView(QTableView):
	def __init__(self, parent, model, on_change):
		super().__init__()

		self.parent = parent
		self.model = model
		self.on_change = on_change

		self.pending_action = None

		self.setModel(model)
		self.setSelectionBehavior(QTableView.SelectRows)
		self.setEditTriggers(QTableView.NoEditTriggers)
		self.setColumnWidth(0, 300)
		self.setColumnWidth(1, 300)

	def keyPressEvent(self, event):
		key = event.text().upper()

		if event.matches(QKeySequence.StandardKey.Save):
			self.parent.save()
			return

		if event.matches(QKeySequence.StandardKey.Find):
			self.find_track()
			return

		if event.matches(QKeySequence.StandardKey.Print):
			self.parent.show_progress()
			return

		if event.matches(QKeySequence.StandardKey.Italic):
			self.parent.import_library()
			return

		if key == " ":
			self.open_links()
			return

		if event.key() == Qt.Key_Tab:
			self.hide_complete_rows()
			return

		indexes = self.selectionModel().selectedRows()
		if not indexes:
			return

		if key == "I":
			self.pending_action = None
			for idx in indexes:
				row = self.model.rows[idx.row()]
				row["Instrumental"] = not row.get("Instrumental", False)
				self.model.dataChanged.emit(self.model.index(idx.row(), 0), self.model.index(idx.row(), len(HEADERS)-1))
			self.on_change()
			return

		if event.matches(QKeySequence.StandardKey.Cancel):
			self.parent.on_mode_change(None)
			self.pending_action = None
			self.show_all_rows()
			return

		if key in [s["key"] for s in LYRIC_SITES.values()]:
			self.parent.on_mode_change(key)
			self.pending_action = key
			return

		for state in STATE_OPTIONS:
			if key == STATE_OPTIONS[state]['key']:

				for idx in indexes:
					row = self.model.rows[idx.row()]
					for site in LYRIC_SITES.items():
						if not self.pending_action or self.pending_action == site[1]["key"]:
							row[site[0]] = state
					self.model.dataChanged.emit(self.model.index(idx.row(), 0), self.model.index(idx.row(), len(HEADERS)-1))
				self.on_change()
				self.parent.on_mode_change(None)
				self.pending_action = None

		# For arrow keys, which we do want normal table behavior for
		if not event.text():
			super().keyPressEvent(event)
			return

	def find_track(self):
		query = QInputDialog.getText(self, "Enter Song Name", "Enter the song name you would like to search for")
		if not query[1]:
			return

		matches = []
		for i in range(len(self.model.rows)):
			row = self.model.rows[i]
			if query[0].lower() in f"{row.get("Artist", "")} {row.get("Name", "")}".lower():
				matches.append(i)

		if not matches:
			QMessageBox.warning(self, "No Matches", "No matches for your search query were found!")
			return

		for i in range(len(self.model.rows)+1):
			if i not in matches:
				self.hideRow(i)

	def open_links(self):
		indexes = self.selectionModel().selectedRows()

		if not indexes:
			QMessageBox.information(self, "No selection", "Select at least one row.")
			return

		for idx in indexes:
			row = self.model.rows[idx.row()]
			artist = row.get("Artist", "")
			name = row.get("Name", "")

			query = urllib.parse.quote_plus(re.sub(r"[\(\)]", "", f"{artist.split(" & ")[0].split(", ")[0]} {name}"))

			for s in LYRIC_SITES.values():
				webbrowser.open(s["url"].replace("{query}", query))

	def hide_complete_rows(self):
		i = 0
		for row in self.model.rows:
			complete = True
			for site in LYRIC_SITES.keys():
				if row[site] != "Complete":
					complete = False

			if complete:
				self.hideRow(i)

			i += 1

	def show_all_rows(self):
		for i in range(len(self.model.rows)):
			self.showRow(i)

class TrackTableModel(QAbstractTableModel):
	def __init__(self, rows, on_change):
		super().__init__()
		self.rows = rows
		self.on_change = on_change

	def rowCount(self, parent=None):
		return len(self.rows)

	def columnCount(self, parent=None):
		return len(HEADERS)

	def data(self, index, role):
		if not index.isValid():
			return None

		row = self.rows[index.row()]
		col = HEADERS[index.column()]

		instrumental = row.get("Instrumental")

		if role == Qt.DisplayRole:
			if col == "Instrumental":
				return "✔" if instrumental else "⊗"
			return str(row.get(col, ""))

		if role == Qt.BackgroundRole:
			if instrumental:
				return None
			
			gradient = QLinearGradient(QPointF(0.0, 0.0), QPointF(1.0, 0.0))
			colors = []
			for site in LYRIC_SITES.keys():
				colors.append(STATE_OPTIONS[row.get(site)]['color'])

			start = 0.25
			end = 0.75
			step = (end-start) / (len(colors)-1)
			i = 0
			for i in range(len(colors)):
				gradient.setColorAt(start+(step*i), colors[i])

			return QBrush(gradient)

		if role == Qt.ForegroundRole and instrumental:
			return QColor("#777")

		return None

	def setData(self, index, value, role):
		row = self.rows[index.row()]
		col = HEADERS[index.column()]

		row[col] = value
		self.dataChanged.emit(index, index)
		self.on_change()
		return True

	def flags(self, index):
		return Qt.ItemIsSelectable | Qt.ItemIsEnabled

	def headerData(self, section, orientation, role):
		if role == Qt.DisplayRole:
			if orientation == Qt.Horizontal:
				return HEADERS[section]
			return section + 1
		return None

class ProgressWindow(QDialog):
	def __init__(self, rows):
		super().__init__()
		self.setWindowTitle("Progress")
		layout = QVBoxLayout()

		self.rows = rows

		self.k = {
			"known": "Known State",
			**{site: f"Completed ({site})" for site in LYRIC_SITES.keys()},
			"all": "Completed (All)"
		}

		self.labels = {key: QLabel() for key in self.k}
		self.bars = {key: QProgressBar() for key in self.k}

		for key in self.k:
			box = QHBoxLayout()
			box.addWidget(QLabel(self.k[key]))
			box.addWidget(self.labels[key])
			box.setAlignment(Qt.AlignJustify)
			layout.addLayout(box)
			layout.addWidget(self.bars[key])

		self.setLayout(layout)
		self.update_progress()

	def get_progress(self):
		total = len(self.rows)

		progress = {
			"known": len([r for r in self.rows if r.get("Instrumental") or all([r.get(site) != "Unknown" for site in LYRIC_SITES.keys()])]),
			"all": len([r for r in self.rows if r.get("Instrumental") or all([r.get(site) == "Complete" for site in LYRIC_SITES.keys()])]),
			**{
				site: len([r for r in self.rows if r.get(site) == "Complete"]) for site in LYRIC_SITES.keys()
			}
		}

		return progress

	def update_progress(self):
		total = len(self.rows)
		progress = self.get_progress()

		for key in self.k:
			self.labels[key].setText(f"{progress[key]} / {total} ({progress[key] / total * 100:0.2f}%)")
			self.bars[key].setValue(int(progress[key] / total * 100))

class App(QMainWindow):
	def __init__(self):
		super().__init__()

		self.setWindowTitle("Lyric Data Editor")
		self.resize(1000, 600)

		self.rows = []
		self.load_csv()

		self.model = TrackTableModel(self.rows, self.on_change)
		self.table = TrackTableView(self, self.model, self.on_change)

		for col in range(len(HEADERS)):
			self.table.setItemDelegateForColumn(col, GradientDelegate(self.table))

		self.save_btn = QPushButton("Save Changes (⌘S)")
		self.save_timer = QTimer()
		self.save_timer.setInterval(60000)
		self.save_timer.setSingleShot(True)
		self.save_timer.timeout.connect(self.save)
		self.has_changes = False

		self.progress_window = None
		self.mode_label = QLabel("")

		self.init_ui()

	def load_csv(self):
		if not os.path.exists('./tracks.csv'):
			self.import_library()
			self.save(force=True)
			return

		with open('./tracks.csv', 'r') as f:
			reader = csv.DictReader(f)
			for row in reader:
				self.rows.append({
					**row,
					"Instrumental": False if row['Instrumental'] == "False" else True
				})

	def import_library(self):
		library_path = QFileDialog.getOpenFileName(self, "Open Apple Music Library.xml", "", "Apple Music XML (*.xml)")[0]
		
		if not library_path:
			return

		new_data = load_library(library_path)

		self.model.beginResetModel()

		# Add rows, ignoring any duplicates
		for new_row in new_data:
			match = False
			for row in self.rows:
				if row['Name'] == new_row['Name'] and row['Artist'] == new_row['Artist']:
					match = True
					break
			if not match:
				self.rows.append(new_row)

		self.model.endResetModel()

	def init_ui(self):
		layout = QVBoxLayout()

		layout.addWidget(self.table)

		controls_layout = QVBoxLayout()

		global_controls_layout = QHBoxLayout()

		find_btn = QPushButton("Find a Track (⌘F)")
		find_btn.clicked.connect(self.table.find_track)

		open_btn = QPushButton("Open Links for Selected (Space)")
		open_btn.clicked.connect(self.table.open_links)

		progress_btn = QPushButton("Show Progress (⌘P)")
		progress_btn.clicked.connect(self.show_progress)

		import_btn = QPushButton("Import Library (⌘I)")
		import_btn.clicked.connect(self.import_library)

		self.save_btn.setEnabled(False)
		self.save_btn.clicked.connect(self.save)

		global_controls_layout.addWidget(find_btn)
		global_controls_layout.addWidget(open_btn)
		global_controls_layout.addWidget(progress_btn)
		global_controls_layout.addWidget(import_btn)
		global_controls_layout.addWidget(self.save_btn)

		help_text_layout = QVBoxLayout()
		self.mode_label.setAlignment(Qt.AlignHCenter)
		self.on_mode_change(None)

		help_label = QLabel(
			"Esc = Reset Filters/Mode, Tab = Show Incomplete Songs Only\nI = Toggle Instumental, " +
			", ".join([f"{site[1]['key']} > ? = Set {site[0]}" for site in LYRIC_SITES.items()]) +
			"\n" + ", ".join([v['key']+" = "+k for k,v in STATE_OPTIONS.items()])
		)
		help_label.setAlignment(Qt.AlignHCenter)
		help_text_layout.addWidget(self.mode_label)
		help_text_layout.addWidget(help_label)
		help_text_layout.setAlignment(help_label, Qt.AlignHCenter)

		layout.addLayout(global_controls_layout)
		layout.addLayout(help_text_layout)

		widget = QWidget()
		widget.setLayout(layout)

		self.setCentralWidget(widget)

	def on_change(self):
		self.setWindowTitle("Lyric Data Editor*")
		self.save_btn.setEnabled(True)
		self.has_changes = True
		self.save_timer.start()
		if self.progress_window:
			self.progress_window.update_progress()

	def on_mode_change(self, mode):
		mode_label = "All"
		for site in LYRIC_SITES.items():
			if mode == site[1]["key"]:
				mode_label = site[0]
				break
		self.mode_label.setText(f"Mode: Modify {mode_label}")

	def show_progress(self):
		if not self.progress_window:
			self.progress_window = ProgressWindow(self.model.rows)
		self.progress_window.show()
		self.progress_window.raise_()

	def save(self, force=False):
		# The save timer activates if there are any changes
		if not (self.has_changes or force):
			return

		self.has_changes = False
		self.save_timer.stop()

		# Make a backup
		os.rename('./tracks.csv', './tracks.csv.bak')

		with open('./tracks.csv', 'w') as f:
			writer = csv.DictWriter(f, fieldnames=HEADERS)
			writer.writeheader()
			writer.writerows(self.rows)

		self.setWindowTitle("Lyric Data Editor")
		self.save_btn.setEnabled(False)

	def closeEvent(self, event):
		self.save(force=True)
		event.accept()

if __name__ == "__main__":
	app = QApplication(sys.argv)
	window = App()
	window.show()
	sys.exit(app.exec())
