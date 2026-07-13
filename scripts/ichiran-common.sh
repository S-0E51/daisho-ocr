#!/bin/sh
# Shared helpers for the native (no-Docker) Ichiran WSL wrappers.
#
# Sourced by ichiran-cli-wsl and ichiran-service-wsl. Provides a single,
# reliable way to bring PostgreSQL up and confirm it is accepting connections.
# All diagnostics go to stderr so wrapper stdout stays clean JSON.

# Database that holds the restored Ichiran dictionary dump.
ICHIRAN_DB="${ICHIRAN_DB:-jmdict}"
# How long (seconds) to wait for PostgreSQL to accept connections after a start.
ICHIRAN_PG_WAIT="${ICHIRAN_PG_WAIT:-30}"

log_err() {
  printf '%s\n' "$*" >&2
}

# Succeeds (exit 0) when PostgreSQL is accepting connections.
postgres_ready() {
  pg_isready -q >/dev/null 2>&1
}

# Try to start the PostgreSQL service, tolerating both systemd and non-systemd
# WSL. Returns 0 if a start command ran (not whether it succeeded); readiness is
# confirmed separately by wait_for_postgres.
start_postgres() {
  if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running >/dev/null 2>&1; then
    sudo systemctl start postgresql >/dev/null 2>&1 && return 0
  fi
  # Non-systemd WSL (the common case): use the SysV service wrapper.
  if command -v service >/dev/null 2>&1; then
    sudo service postgresql start >/dev/null 2>&1 && return 0
  fi
  # Last resort: pg_ctlcluster for a default cluster if present.
  if command -v pg_ctlcluster >/dev/null 2>&1; then
    cluster="$(pg_lsclusters -h 2>/dev/null | awk 'NR==1 {print $1"/"$2}')"
    if [ -n "$cluster" ]; then
      ver="${cluster%/*}"
      name="${cluster#*/}"
      sudo pg_ctlcluster "$ver" "$name" start >/dev/null 2>&1 && return 0
    fi
  fi
  return 1
}

# Ensure PostgreSQL is up and accepting connections, starting it if needed.
# Prints an actionable message and returns non-zero on failure.
ensure_postgres() {
  if postgres_ready; then
    return 0
  fi

  start_postgres || true

  count=0
  while [ "$count" -lt "$ICHIRAN_PG_WAIT" ]; do
    if postgres_ready; then
      return 0
    fi
    count=$((count + 1))
    sleep 1
  done

  log_err "Ichiran error: PostgreSQL is not accepting connections after ${ICHIRAN_PG_WAIT}s."
  log_err "Try: wsl -d Ubuntu -- sudo service postgresql start"
  log_err "Or re-run setup_ichiran_wsl.ps1 to reprovision the native Ichiran install."
  return 1
}
