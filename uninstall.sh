#!/bin/zsh
# Remove the daily schedule installed by install.sh. Your hunt dir, config and ~/.local/state/jobhunt are left alone.
set -u
launchctl bootout "gui/$(id -u)/local.jobhunt" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/local.jobhunt.plist"
rm -rf "$HOME/Applications/JobHunt.app"
echo "schedule removed"
