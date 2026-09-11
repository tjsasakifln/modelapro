import os
import sys
import matplotlib

# Set matplotlib backend to Agg to avoid GUI issues
matplotlib.use('Agg')

# Add project root to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
