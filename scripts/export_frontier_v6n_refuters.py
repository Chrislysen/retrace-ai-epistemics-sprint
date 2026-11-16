"""Export all300 first-attempt controlled-seed proposals, without gold labels."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.frontier_v6n_products import export_main
if __name__=='__main__':export_main('refuter-catalog')
