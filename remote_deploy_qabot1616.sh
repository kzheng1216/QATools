#!/usr/bin/env bash
# Deploy QATools to qabot16 (10.64.16.16).
#
# The app that serves qabot16's QA Hub UI runs INSIDE the
# roku-automation-framework container, from /workspaces/automation-ide/mycode/QATools
# (a bind mount of /home/qauser/workspaces/automation-ide/mycode/QATools on the
# host). So the deploy targets the container: the former host-path deploy to
# /home/qauser/QATools updated a copy that nothing user-facing was running.
#
# Ports (published by the container): backend 9888, frontend 9898.
#
# Usage:
#   ./remote_deploy_qabot16.sh
set -euo pipefail

cd "$(dirname "$0")"

REMOTE="qauser@10.64.16.16"
# Identify the container by image reference; remote_deploy.sh resolves an image,
# a container name, or an id to the running container.
CONTAINER="eswat-docker-dev-local.artifactory.tools.roku.com/roku-automation-framework:latest"
CONTAINER_QATOOLS="/workspaces/automation-ide/mycode/QATools"
SSH_PASS='roku!!123'

echo "Deploying QATools to qabot16 (container) ..."
./remote_deploy.sh -c "$CONTAINER" "$REMOTE" "$CONTAINER_QATOOLS" "$SSH_PASS"
echo "QATools deployment to qabot16 complete"
echo "  backend:  http://10.64.16.16:9888"
echo "  frontend: http://10.64.16.16:9898"
