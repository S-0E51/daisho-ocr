"""
Theme - Dark theme constants and stylesheets for 代書.
"""

# Color palette
BG_PRIMARY = "#0f0d0d"
BG_SECONDARY = "#151111"
BG_TERTIARY = "#1b1515"
BG_BUTTON = "#1f1717"
BG_BUTTON_HOVER = "#2a1d1d"
BG_BUTTON_PRESSED = "#170f0f"
BG_DISABLED = "#141010"

TEXT_PRIMARY = "#ebe1d9"
TEXT_SECONDARY = "#9e9188"
TEXT_DISABLED = "#6f645f"

ACCENT = "#bf4545"
ACCENT_HOVER = "#d35454"

BORDER = "#392929"
BORDER_LIGHT = "#4d3535"

SUCCESS = "#82b978"
ERROR = "#d36b6b"
WARNING = "#c99763"

# Font families for Japanese text
JAPANESE_FONTS = "'Yu Gothic UI', 'Meiryo', 'Consolas', sans-serif"

MAIN_WINDOW_STYLE = f"""
    QMainWindow {{
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #0d0d0d,
            stop: 0.5 #121010,
            stop: 1 #0a0a0a
        );
    }}
    QWidget {{
        background-color: transparent;
        color: {TEXT_PRIMARY};
        font-family: {JAPANESE_FONTS};
        font-size: 12px;
    }}
    QWidget#rootContainer {{
        background-color: transparent;
    }}
    QWidget#heroPanel {{
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #191212,
            stop: 1 #120f0f
        );
        border: 1px solid {BORDER_LIGHT};
        border-radius: 10px;
    }}
    QLabel#heroTitle {{
        color: #ef5c5c;
        font-size: 32px;
        font-weight: 700;
        letter-spacing: 1px;
    }}
    QLabel#heroSubtitle {{
        color: #c7bbb3;
        font-size: 13px;
        font-weight: 500;
    }}
    QLabel#stepText {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
    }}
    QLabel#chip {{
        color: #fff3ee;
        background-color: #2a1d1d;
        border: 1px solid {BORDER_LIGHT};
        border-radius: 12px;
        padding: 3px 10px;
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel#statusMuted {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
    }}
    QLabel#resultsMeta {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
        font-style: italic;
    }}
    QLabel#sectionHint {{
        color: {TEXT_SECONDARY};
        font-size: 11px;
    }}
    QPushButton {{
        background-color: {BG_BUTTON};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_LIGHT};
        padding: 8px 14px;
        border-radius: 4px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {BG_BUTTON_HOVER};
        border-color: {ACCENT};
    }}
    QPushButton:pressed {{
        background-color: {BG_BUTTON_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: {BG_DISABLED};
        color: {TEXT_DISABLED};
        border-color: {BORDER};
    }}
    QPushButton#primary {{
        background-color: {ACCENT};
        border-color: {ACCENT_HOVER};
        color: #fff5f1;
    }}
    QPushButton#primary:hover {{
        background-color: {ACCENT_HOVER};
    }}
    QPushButton#secondary {{
        border-color: #7f4040;
    }}
    QPushButton#ghost {{
        background-color: #181212;
        border-color: #3a2828;
        color: #bcaea5;
    }}
    QPushButton#ghost:hover {{
        border-color: {ACCENT};
        color: #e7d9cf;
    }}
    QTextEdit, QPlainTextEdit {{
        background-color: {BG_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 9px;
        font-family: {JAPANESE_FONTS};
        font-size: 14px;
        selection-background-color: {ACCENT};
    }}
    QTextEdit#resultsArea, QPlainTextEdit#resultsArea {{
        background-color: #141010;
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 10px;
    }}
    QGroupBox {{
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #171313,
            stop: 1 #1b1717
        );
        border: 1px solid {BORDER};
        border-radius: 6px;
        margin-top: 14px;
        padding: 12px 10px 10px 10px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: {ACCENT};
        background-color: #171313;
    }}
    QComboBox {{
        background-color: {BG_SECONDARY};
        border: 1px solid {BORDER};
        border-radius: 4px;
        padding: 5px 10px;
    }}
    QComboBox:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #c6b8af;
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #181212;
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT};
        selection-color: #fff6f2;
    }}
    QStatusBar {{
        background-color: {BG_SECONDARY};
        color: {TEXT_SECONDARY};
        border-top: 1px solid {BORDER};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QToolTip {{
        background-color: #1c1414;
        color: #f2e7df;
        border: 1px solid #a63a3a;
        padding: 4px;
    }}
    QScrollBar:vertical {{
        background: #151111;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #523838;
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #7a4a4a;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
"""

MAIN_STATUS_BASE_STYLE = "font-size: 14px; color: #d9cec6; font-weight: 600;"
MAIN_STATUS_SUCCESS_STYLE = f"font-size: 14px; color: {SUCCESS}; font-weight: 600;"
MAIN_STATUS_ERROR_STYLE = f"font-size: 14px; color: {ERROR}; font-weight: 600;"
MAIN_AUX_LABEL_STYLE = "color: #9e9188; font-size: 11px;"

SETTINGS_DIALOG_STYLE = f"""
    QDialog {{
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #0d0d0d,
            stop: 0.5 #111111,
            stop: 1 #0a0a0a
        );
        color: #e8dfd8;
        font-family: 'Consolas', 'Cascadia Code', 'Yu Gothic UI', sans-serif;
        font-size: 12px;
    }}
    QWidget {{
        background-color: transparent;
        color: #e8dfd8;
    }}
    QTabWidget::pane {{
        background-color: #121010;
        border: 1px solid #352828;
        border-radius: 6px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: #191515;
        color: #b7aba2;
        padding: 8px 14px;
        border: 1px solid #2f2424;
        border-bottom: none;
        margin-right: 4px;
        border-top-left-radius: 5px;
        border-top-right-radius: 5px;
        min-width: 80px;
    }}
    QTabBar::tab:selected {{
        background-color: #221717;
        color: #f1e7df;
        border-color: #4e2f2f;
    }}
    QTabBar::tab:hover:!selected {{
        background-color: #261b1b;
        color: #e1d3c9;
    }}
    QGroupBox {{
        background-color: qlineargradient(
            x1: 0, y1: 0, x2: 1, y2: 1,
            stop: 0 #171313,
            stop: 1 #1b1717
        );
        border: 1px solid #302323;
        border-radius: 6px;
        margin-top: 16px;
        padding: 16px 12px 12px 12px;
        color: #e8dfd8;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #d24a4a;
        background-color: #171313;
    }}
    QLabel {{
        color: #e8dfd8;
        background-color: transparent;
        border: none;
    }}
    QLineEdit, QTextEdit, QComboBox {{
        background-color: #131010;
        border: 1px solid #3a2a2a;
        border-radius: 4px;
        padding: 6px 7px;
        color: #efe5de;
        selection-background-color: #b83a3a;
    }}
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
        border: 1px solid #d24a4a;
        background-color: #171212;
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #c6b8af;
        margin-right: 6px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #181212;
        color: #efe5de;
        border: 1px solid #3a2a2a;
        selection-background-color: #b83a3a;
        selection-color: #fff6f2;
    }}
    QPushButton {{
        background-color: #1d1717;
        border: 1px solid #4a3232;
        border-radius: 4px;
        padding: 7px 12px;
        color: #e8dfd8;
    }}
    QPushButton:hover {{
        background-color: #271b1b;
        border-color: #b83a3a;
    }}
    QPushButton:pressed {{
        background-color: #150f0f;
    }}
    QPushButton#primary {{
        background-color: #b83a3a;
        border-color: #cb4d4d;
        color: #fff5f1;
        font-weight: bold;
    }}
    QPushButton#primary:hover {{
        background-color: #cf4b4b;
    }}
    QPushButton#secondary {{
        border-color: #7f4040;
    }}
    QCheckBox {{
        color: #e8dfd8;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        background-color: #131010;
        border: 1px solid #4a3333;
        border-radius: 3px;
    }}
    QCheckBox::indicator:hover {{
        border-color: #b83a3a;
    }}
    QCheckBox::indicator:checked {{
        background-color: #b83a3a;
        border-color: #d24a4a;
    }}
    QScrollBar:vertical {{
        background: #151111;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: #523838;
        min-height: 24px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #7a4a4a;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QToolTip {{
        background-color: #1c1414;
        color: #f2e7df;
        border: 1px solid #a63a3a;
        padding: 4px;
    }}
"""

# Settings dialog helper styles
SETTINGS_ACCENT = "#d24a4a"
SETTINGS_MUTED_LABEL_STYLE = "color: #a0938b; font-size: 10px;"
SETTINGS_SUCCESS_LABEL_STYLE = "color: #82b978; font-size: 10px;"
SETTINGS_WARNING_LABEL_STYLE = "color: #c99763; font-size: 10px;"
SETTINGS_TITLE_STYLE = "font-size: 24px; font-weight: bold; color: #f3e8df;"
SETTINGS_SUBTITLE_STYLE = "font-size: 14px; color: #a0938b;"
HOTKEY_EDIT_RECORDING_STYLE = (
    "background-color: #2a1414; "
    "border: 1px solid #d24a4a; "
    "color: #ffd7d1;"
)
HOTKEY_EDIT_IDLE_STYLE = (
    "background-color: #131010; "
    "border: 1px solid #3a2a2a; "
    "color: #efe5de;"
)
