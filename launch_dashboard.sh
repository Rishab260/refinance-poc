#!/bin/bash
# Launch Jupyter Notebook Dashboard
# Usage: bash launch_dashboard.sh

echo "======================================================================"
echo "  Refi-Ready POC - Jupyter Notebook Dashboard Launcher"
echo "======================================================================"
echo ""

# Check if Jupyter is installed
if ! command -v jupyter &> /dev/null; then
    echo "⚠️  Jupyter is not installed. Installing now..."
    pip install jupyter notebook -q
    if [ $? -eq 0 ]; then
        echo "✓ Jupyter installed successfully!"
    else
        echo "✗ Failed to install Jupyter. Please install manually:"
        echo "   pip install jupyter notebook"
        exit 1
    fi
else
    echo "✓ Jupyter Notebook is installed"
fi

echo ""
echo "🚀 Launching Jupyter Notebook..."
echo ""
echo "The dashboard will open in your browser at: http://localhost:8888"
echo ""
echo "📖 Instructions:"
echo "   1. Click on 'refi_dashboard.ipynb' in the file browser"
echo "   2. Click 'Cell' → 'Run All' to generate all visualizations"
echo "   3. Scroll through to explore your data!"
echo ""
echo "Press Ctrl+C to stop the Jupyter server when done."
echo ""
echo "======================================================================"

# Launch Jupyter Notebook
jupyter notebook refi_dashboard.ipynb
