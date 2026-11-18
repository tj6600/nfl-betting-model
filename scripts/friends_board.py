"""Friends page: save this week's NFL board legs, grade finished ones (free nflverse data), build board/site/friends.html.

  python scripts/friends_board.py [--no-grade]
Run by .github/workflows/friends.yml after every NFL board push and on a daily schedule. No Odds API key, no credits.
"""
import os, sys, argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import friends

ap = argparse.ArgumentParser()
ap.add_argument('--no-grade', action='store_true')
friends.run(grade_it=not ap.parse_args().no_grade)
