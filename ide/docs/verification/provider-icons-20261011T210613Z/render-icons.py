"""Render a gallery of the shipped SVGs; no app/controller/account is loaded."""
import sys
from pathlib import Path
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QLabel, QComboBox, QFrame
from ui.theme import apply_theme
from ui.icons import provider_icon

app = QApplication([])
apply_theme(app)
w = QMainWindow()
w.resize(1080, 430)
body = QWidget()
w.setCentralWidget(body)
layout = QVBoxLayout(body)
layout.setContentsMargins(28, 24, 28, 24)
layout.setSpacing(20)
header = QLabel("Iconos de proveedores")
header.setStyleSheet("font-size: 24px; font-weight: 700;")
layout.addWidget(header)
layout.addWidget(QLabel("SVG incluidos en ISyCode IDE · colores originales y variantes claras"))
row = QHBoxLayout()
row.addWidget(QLabel("Barra superior"))
combo = QComboBox()
combo.setIconSize(QSize(22, 22))
combo.addItem(provider_icon("nvidia"), "nvidia · API")
combo.setFixedWidth(200)
row.addWidget(combo)
model = QComboBox()
model.addItem("nvidia/nemotron-3-ultra-550b-a55b")
model.setFixedWidth(380)
row.addWidget(model)
row.addStretch()
layout.addLayout(row)
grid = QGridLayout()
grid.setSpacing(10)
brands = [("nvidia", "NVIDIA"), ("openai", "OpenAI / ChatGPT"), ("claude", "Claude"), ("anthropic", "Anthropic"), ("google", "Gemini"), ("grok", "Grok"), ("groq", "Groq"), ("deepseek", "DeepSeek"), ("mistral", "Mistral"), ("openrouter", "OpenRouter"), ("ollama", "Ollama"), ("lmstudio", "LM Studio")]
for i, (brand, text) in enumerate(brands):
 card = QFrame()
 card.setObjectName("logoPreviewCard")
 card.setStyleSheet("QFrame#logoPreviewCard {background:#182433; border:1px solid #2c435b; border-radius:8px;}")
 box = QHBoxLayout(card)
 box.setContentsMargins(16, 10, 16, 10)
 logo = QLabel()
 logo.setPixmap(provider_icon(brand, size=28).pixmap(28, 28))
 box.addWidget(logo)
 box.addWidget(QLabel(text), 1)
 grid.addWidget(card, i // 4, i % 4)
layout.addLayout(grid)
layout.addWidget(QLabel("Muestra de assets y widgets Qt · datos de ejemplo · no es captura de una cuenta conectada"))
w.show()
app.processEvents()
w.grab().save(str(Path(__file__).with_name("provider-icons-preview.png")))
