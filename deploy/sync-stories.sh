#!/bin/bash
# sync-stories.sh — Sync the local story archive to the GCP VM
#
# Usage (from your local machine):
#   bash deploy/sync-stories.sh
#   bash deploy/sync-stories.sh "Extra_Credit"       # sync one story only
#   bash deploy/sync-stories.sh --dry-run             # preview what would sync
#
# Requires: gcloud CLI authenticated, VM instance 'pawpoller' in us-east1-c
#
# What gets synced:
#   Local:  C:\Users\rhysc\claude\m_x\Archives\Complete_Stories\
#   Remote: /home/kithetiger/story-archive/
#
# Only syncs files needed for posting (BBCode, HTML, PDF, Markdown, Tags, Chapters).
# Excludes backups, drafts, and large binary files.

set -e

INSTANCE="pawpoller"
ZONE="us-east1-c"
VM_USER="kithetiger"
REMOTE_DIR="/home/kithetiger/story-archive"

# Local archive path — adjust if your archive is elsewhere
LOCAL_ARCHIVE="/c/Users/rhysc/claude/m_x/Archives/Complete_Stories"

# Check if running in Git Bash / MSYS on Windows
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    LOCAL_ARCHIVE="/c/Users/rhysc/claude/m_x/Archives/Complete_Stories"
fi

# Handle arguments
STORY_FILTER=""
DRY_RUN=""
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN="--dry-run"
        echo "DRY RUN — no files will be transferred"
    else
        STORY_FILTER="$arg"
    fi
done

if [[ ! -d "$LOCAL_ARCHIVE" ]]; then
    echo "Error: Local archive not found at $LOCAL_ARCHIVE"
    echo "Update LOCAL_ARCHIVE in this script to point to your Complete_Stories directory."
    exit 1
fi

# Build the source path
if [[ -n "$STORY_FILTER" && "$STORY_FILTER" != "--dry-run" ]]; then
    SOURCE="$LOCAL_ARCHIVE/$STORY_FILTER/"
    if [[ ! -d "$SOURCE" ]]; then
        echo "Error: Story folder not found: $SOURCE"
        exit 1
    fi
    echo "Syncing story: $STORY_FILTER"
else
    SOURCE="$LOCAL_ARCHIVE/"
    echo "Syncing entire archive"
fi

echo "Local:  $SOURCE"
echo "Remote: $VM_USER@$INSTANCE:$REMOTE_DIR/"
echo ""

# Use gcloud compute scp for the transfer
# --recurse: sync directories
# Exclude patterns to skip unnecessary files
gcloud compute scp --zone="$ZONE" --recurse \
    "$SOURCE" \
    "$VM_USER@$INSTANCE:$REMOTE_DIR/" \
    $DRY_RUN

echo ""
echo "Sync complete."

# Fix permissions so the Docker container (UID 1001) can read the files
echo "Fixing permissions..."
gcloud compute ssh "$INSTANCE" --zone="$ZONE" --command="sudo chmod -R o+rX $REMOTE_DIR"

echo "Done. Stories available at $REMOTE_DIR/ inside Docker as /app/story-archive/"
