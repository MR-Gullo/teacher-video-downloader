"""Path-relative host bootstrap. Included in the sealed payload before signing."""
from pathlib import Path
import runpy
import sys

source = Path(__file__).resolve().parents[1] / 'companion'
sys.path.insert(0, str(source))
runpy.run_path(str(source / 'host.py'), run_name='__main__')
