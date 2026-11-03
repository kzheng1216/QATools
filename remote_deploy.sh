#!/usr/bin/env bash
# Deploy ALL of QATools (every file/dir under this directory) to a remote
# server, excluding only VCS/build/runtime noise. Uses rsync over ssh. After the
# sync it restarts the remote backend then frontend so the new code takes effect.
#
# Two deployment targets are supported:
#
#   HOST MODE (default)      the remote path is a plain directory on the host,
#                            and the services are restarted over ssh.
#
#   CONTAINER MODE (-c)      the remote path lives inside a running Docker
#                            container, and the services are restarted with
#                            `docker exec`. The container is identified by name,
#                            id, or image reference.
#
# Usage:
#   ./remote_deploy.sh [-c <container|image>] <user@host> <remote_root_dir> [ssh_password]
#
# Examples:
#   # host deploy
#   ./remote_deploy.sh qauser@10.64.16.16 /home/qauser/QATools
#   ./remote_deploy.sh qauser@10.64.16.16 /home/qauser/QATools 'roku!!123'
#
#   # container deploy (by container name)
#   ./remote_deploy.sh -c automation-ide \
#       qauser@10.64.16.16 /workspaces/automation-ide/mycode/QATools 'roku!!123'
#
#   # container deploy (by image reference; resolved to its running container)
#   ./remote_deploy.sh -c eswat-docker-dev-local.artifactory.tools.roku.com/roku-automation-framework:latest \
#       qauser@10.64.16.16 /workspaces/automation-ide/mycode/QATools 'roku!!123'
#
# In container mode <remote_root_dir> is the path as seen INSIDE the container.
# When that path comes from a bind mount, the files are rsync'ed straight to the
# host side of the mount (fast, and no docker cp needed); otherwise they are
# staged in /tmp on the host and copied in with `docker cp`.
#
# If ssh_password is omitted, normal ssh auth (keys / agent / prompt) is used.
set -euo pipefail

CONTAINER=""
while getopts ":c:h" opt; do
    case "$opt" in
        c) CONTAINER="$OPTARG" ;;
        h) sed -n '2,37p' "$0"; exit 0 ;;
        \?) echo "ERROR: unknown option -$OPTARG" >&2; exit 1 ;;
        :) echo "ERROR: option -$OPTARG requires an argument" >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

REMOTE="${1:-}"
REMOTE_ROOT="${2:-}"
SSH_PASS="${3:-}"

if [[ -z "$REMOTE" || -z "$REMOTE_ROOT" ]]; then
    echo "Usage: $0 [-c <container|image>] <user@host> <remote_root_dir> [ssh_password]" >&2
    exit 1
fi

# Local QATools dir = this script's directory. The whole tree is deployed.
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Exclude VCS, editor/type caches, build/runtime artifacts, and the runtime data
# directory. Everything else under QATools (config, 4_runcase, 1_create_test_plan,
# 5_activate, 80_tools, 99_result_history, root scripts, ...) is deployed.
# NOTE: /data holds the remote's own runtime state (runcase_report, testrail_data,
# analyzer_history, agent_session, skill_data, docs, file_transfer) and must NOT
# be overwritten or deleted by a deploy.
# NOTE: .venv / bot_env are native virtualenvs built ON the target. They must
# never be synced: pushing a locally-built venv over a different CPU
# architecture (or Python build) replaces the native .so files and the backend
# then fails to import (e.g. "bcrypt/_bcrypt.abi3.so: cannot open shared object
# file"). The target keeps and reuses its own.
EXCLUDES=(
    "--exclude=.git"
    "--exclude=.eggs"
    "--exclude=.mypy_cache"
    "--exclude=.pytest_cache"
    "--exclude=.ruff_cache"
    "--exclude=node_modules"
    "--exclude=dist"
    "--exclude=.vite"
    "--exclude=__pycache__"
    "--exclude=*.pyc"
    "--exclude=logs"
    "--exclude=*.log"
    "--exclude=*.Identifier"
    "--exclude=/data"
    "--exclude=.venv"
    "--exclude=bot_env"
)

# Wrap ssh with sshpass if a password was given.
SSH_CMD="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
RSYNC_RSH="$SSH_CMD"
SSHPASS_PREFIX=()
if [[ -n "$SSH_PASS" ]]; then
    if command -v sshpass >/dev/null 2>&1; then
        SSHPASS_PREFIX=(sshpass -p "$SSH_PASS")
    else
        echo "ERROR: a password was given but 'sshpass' is not installed here." >&2
        echo "Fix one of:" >&2
        echo "  1) Install sshpass:  apt-get update && apt-get install -y sshpass" >&2
        echo "  2) Or omit the password and use an SSH key:" >&2
        echo "       ssh-copy-id $REMOTE   # then re-run without the password arg" >&2
        exit 1
    fi
fi

# Run a command on the remote host.
rsh() { "${SSHPASS_PREFIX[@]}" $SSH_CMD "$REMOTE" "$@"; }

#
# ----------------------------- HOST MODE -----------------------------
#
if [[ -z "$CONTAINER" ]]; then
    echo "Deploying ALL of QATools -> ${REMOTE}:${REMOTE_ROOT}"
    echo "  from: $LOCAL_DIR"
    echo "  excluding: .git, caches, node_modules, dist, __pycache__, logs, *.log, /data, .venv"

    rsh "mkdir -p '$REMOTE_ROOT'"

    # Trailing slash on source: copy the CONTENTS of QATools/ into the remote root.
    # --delete keeps the remote a mirror (removes files no longer present locally,
    # except anything matched by EXCLUDES, which is left untouched on the remote).
    echo "  syncing whole tree ..."
    "${SSHPASS_PREFIX[@]}" rsync -az --delete "${EXCLUDES[@]}" \
        -e "$RSYNC_RSH" \
        "$LOCAL_DIR/" \
        "$REMOTE:$REMOTE_ROOT/"

    echo "Deploy complete: ${REMOTE}:${REMOTE_ROOT}"

    # Restart backend then frontend so the freshly-synced code takes effect. Each
    # restart.sh calls its sibling ./shutdown.sh + ./startup.sh with relative paths,
    # so run it from that service's own directory.
    echo "Restarting backend ..."
    rsh "cd '$REMOTE_ROOT/backend' && bash restart.sh"

    echo "Restarting frontend ..."
    rsh "cd '$REMOTE_ROOT/frontend' && bash restart.sh"

    echo "Restart complete: ${REMOTE}:${REMOTE_ROOT}"
    exit 0
fi

#
# --------------------------- CONTAINER MODE ---------------------------
#
echo "Deploying ALL of QATools -> ${REMOTE} container '${CONTAINER}':${REMOTE_ROOT}"
echo "  from: $LOCAL_DIR"
echo "  excluding: .git, caches, node_modules, dist, __pycache__, logs, *.log, /data, .venv"

# docker may need sudo depending on the remote user's groups; probe once and
# reuse the same prefix for every docker call.
DOCKER="$(rsh 'if docker info >/dev/null 2>&1; then echo docker; elif sudo -n docker info >/dev/null 2>&1; then echo "sudo docker"; else echo NONE; fi' | tr -d "\r")"
if [[ "$DOCKER" == "NONE" || -z "$DOCKER" ]]; then
    echo "ERROR: cannot run docker on $REMOTE (neither 'docker' nor passwordless 'sudo docker')." >&2
    exit 1
fi

# Resolve the container: accept a name/id, or an image reference (the user-facing
# identifier is often the image, which is not a valid --name filter).
CID="$(rsh "$DOCKER ps -q -f name='^/${CONTAINER}\$' | head -1" | tr -d "\r")"
if [[ -z "$CID" ]]; then
    CID="$(rsh "$DOCKER ps -q -f id='${CONTAINER}' | head -1" | tr -d "\r")"
fi
if [[ -z "$CID" ]]; then
    CID="$(rsh "$DOCKER ps -q --filter ancestor='${CONTAINER}' | head -1" | tr -d "\r")"
fi
if [[ -z "$CID" ]]; then
    echo "ERROR: no RUNNING container matches '${CONTAINER}' (tried name, id, image) on $REMOTE." >&2
    echo "Running containers:" >&2
    rsh "$DOCKER ps --format '  {{.ID}}  {{.Names}}  {{.Image}}'" >&2 || true
    exit 1
fi
CNAME="$(rsh "$DOCKER inspect -f '{{.Name}}' $CID" | tr -d "\r/" )"
echo "  container: $CNAME ($CID)"

# Prefer the host side of a bind mount: rsync straight there, so the files land
# in the container without docker cp. Longest-prefix match so a nested mount wins.
HOST_PATH="$(rsh "$DOCKER inspect -f '{{range .Mounts}}{{.Destination}}|{{.Source}}{{println}}{{end}}' $CID" \
    | tr -d "\r" \
    | awk -F'|' -v d="$REMOTE_ROOT" '
        $1 != "" && (d == $1 || index(d, $1 "/") == 1) {
            if (length($1) > best) { best = length($1); src = $2; dst = $1 }
        }
        END { if (src != "") print src substr(d, length(dst) + 1) }')"

if [[ -n "$HOST_PATH" ]]; then
    echo "  bind mount detected -> syncing via host path: $HOST_PATH"
    rsh "mkdir -p '$HOST_PATH'"
    # --no-times/--omit-dir-times: shared mounts are often root-owned, and
    # failing to set timestamps would otherwise abort rsync with exit 23.
    "${SSHPASS_PREFIX[@]}" rsync -rlpz --delete --no-times --omit-dir-times "${EXCLUDES[@]}" \
        -e "$RSYNC_RSH" \
        "$LOCAL_DIR/" \
        "$REMOTE:$HOST_PATH/"
else
    # No bind mount: stage on the host, then copy into the container. docker cp
    # has no --delete, so stale files inside the container are not removed.
    STAGE="/tmp/qatools-deploy-$$"
    echo "  no bind mount -> staging on host then 'docker cp' into the container"
    echo "  NOTE: docker cp cannot delete; files removed locally stay in the container."
    rsh "rm -rf '$STAGE' && mkdir -p '$STAGE'"
    "${SSHPASS_PREFIX[@]}" rsync -az --delete "${EXCLUDES[@]}" \
        -e "$RSYNC_RSH" \
        "$LOCAL_DIR/" \
        "$REMOTE:$STAGE/"
    rsh "$DOCKER exec $CID mkdir -p '$REMOTE_ROOT'"
    # "/." copies the directory CONTENTS into the destination.
    rsh "$DOCKER cp '$STAGE/.' '$CID:$REMOTE_ROOT'"
    rsh "rm -rf '$STAGE'"
fi

echo "Deploy complete: ${REMOTE} container '${CNAME}':${REMOTE_ROOT}"

# Start (or restart) the services INSIDE the container. restart.sh runs
# shutdown.sh + startup.sh with relative paths, so it must run from the
# service's own directory. startup.sh is idempotent enough that restart.sh also
# covers the "not running yet" case.
for svc in backend frontend; do
    if ! rsh "$DOCKER exec $CID test -f '$REMOTE_ROOT/$svc/restart.sh'"; then
        echo "WARNING: $REMOTE_ROOT/$svc/restart.sh not found in the container; skipping $svc" >&2
        continue
    fi
    echo "Restarting $svc in container ..."
    rsh "$DOCKER exec -w '$REMOTE_ROOT/$svc' $CID bash restart.sh"
done

echo "Restart complete: ${REMOTE} container '${CNAME}':${REMOTE_ROOT}"
