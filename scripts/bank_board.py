"""Build the Bank Builder page (board/site/bank.html) from the three built boards; see bank.py.

  python scripts/bank_board.py [--no-log]     # --no-log: rebuild the page and record only, save no slips
The NFL, NBA and NHL board scripts run this at the end of every build, so it needs no scheduled task of its own.
"""
import os, sys, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import bank

ap = argparse.ArgumentParser()
ap.add_argument('--no-log', action='store_true')
bank.build(log_it=not ap.parse_args().no_log)
