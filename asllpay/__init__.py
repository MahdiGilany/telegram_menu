import sys
from pathlib import Path

# Add the parent directory of 'asll_pay' to sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from .asll_pay_menu import *
from .main import *