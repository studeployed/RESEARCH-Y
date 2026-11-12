"""Source inspected by the graphical contract tests across shared and harness modules."""
from inspect import getsource

from research_y.desktop.actions import perform_action
from research_y.desktop.project_panel import render_project_panel
from tools.gui_feasibility.real_project_app import run


def project_ui_source():
    return '\n'.join(map(getsource, (perform_action, render_project_panel, run)))
