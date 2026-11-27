import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow
from ui.app import AppController
import tempfile

app = QApplication([])
tmp = tempfile.mkdtemp()
c = AppController(tmp)
w = MainWindow(controller=c)

# Check provider/model combos
print('Providers in combo:', [w.provider_combo.itemText(i) for i in range(w.provider_combo.count())])
w.provider_combo.setCurrentText('NVIDIA')
print('Models for NVIDIA:', [w.model_combo.itemText(i) for i in range(w.model_combo.count())])

w.close()
app.quit()
print('UI test passed')