#!/usr/bin/env bash
# Run on your own machine. Walks through the demo's secrets, checking each one,
# applies every migration to the demo database, and writes the server's env file.
# Secrets are never echoed and never appear in a command line.
# Usage: bash deploy/configure.sh ubuntu@SERVER_IP
set -euo pipefail

SERVER="${1:?Usage: bash deploy/configure.sh ubuntu@SERVER_IP}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/loupe_oracle}"
FRONTEND_ORIGIN="${FRONTEND_ORIGIN:-http://localhost:3000}"
cd "$(dirname "$0")/.."
# psql ships with Postgres.app on macOS but is not on the PATH by default.
export PATH="/Applications/Postgres.app/Contents/Versions/latest/bin:$PATH"
command -v psql >/dev/null || { echo "psql is required." >&2; exit 1; }

bold=$'\e[1m' dim=$'\e[2m' red=$'\e[31m' green=$'\e[32m' reset=$'\e[0m'

# Prints where to find a value, then reads it until the check function accepts it.
# Whitespace is stripped from pasted values unless the fifth argument is set.
ask() {
  local title=$1 where=$2 check=$3 secret=${4:-} verbatim=${5:-} value problem
  printf '\n%s%s%s\n%s%s%s\n' "$bold" "$title" "$reset" "$dim" "$where" "$reset" >&2
  while true; do
    if [[ -n "$secret" ]]; then
      read -r -s -p "> (hidden as you paste) " value; echo >&2
    else
      read -r -p "> " value
    fi
    [[ -n "$verbatim" ]] || value=$(printf '%s' "$value" | tr -d '[:space:]')
    if problem=$("$check" "$value"); then
      printf '%sOK%s\n' "$green" "$reset" >&2
      printf '%s' "$value"
      return
    fi
    printf '%s%s Try again.%s\n' "$red" "$problem" "$reset" >&2
  done
}

pooler_pattern='^postgresql://([^:/@]+):\[YOUR-PASSWORD\]@([^:/@]+):([0-9]+)/([^?]+)$'
check_pooler() {
  [[ $1 == postgresql://* ]] || { echo "It should start with postgresql://"; return 1; }
  [[ $1 == *pooler.supabase.com* ]] || { echo "That is not the Session pooler string."; return 1; }
  [[ $1 == *"[YOUR-PASSWORD]"* ]] || { echo "Leave [YOUR-PASSWORD] in it; the password is asked next."; return 1; }
  [[ $1 =~ $pooler_pattern ]] || { echo "Copy the URI exactly as shown, with nothing added."; return 1; }
}
check_project_url() {
  [[ $1 =~ ^https://[a-z0-9]+\.supabase\.co(/.*)?$ ]] || { echo "It should look like https://abcd.supabase.co"; return 1; }
}
check_service_key() {
  if [[ $1 == sb_publishable_* ]]; then echo "That is the publishable key; use the secret one."; return 1; fi
  if [[ $1 == sb_secret_* ]]; then return 0; fi
  [[ $1 == eyJ* ]] || { echo "That does not look like a Supabase key."; return 1; }
  local payload=${1#*.} role
  payload=${payload%%.*}
  role=$(PAYLOAD="$payload" python3 -c 'import base64, json, os
p = os.environ["PAYLOAD"]; p += "=" * (-len(p) % 4)
print(json.loads(base64.urlsafe_b64decode(p)).get("role", ""))' 2>/dev/null || true)
  [[ $role == service_role ]] || { echo "That is the ${role:-unknown} key; use service_role."; return 1; }
}
check_anthropic_key() {
  [[ $1 == sk-ant-* ]] || { echo "Anthropic keys start with sk-ant-"; return 1; }
}
check_nonempty() { [[ -n $1 ]] || { echo "Nothing was entered."; return 1; }; }

echo "${bold}Loupe demo setup.${reset} Five values, with directions for each. Secrets never show on screen."

pooler_url=$(ask "1/5  Supabase connection string" \
"In Supabase, open the loupe-demo project and click Connect at the top.
Open the Session pooler tab and copy the URI exactly as shown. It contains [YOUR-PASSWORD]; leave that in." \
check_pooler)

# psql reads the password from a private file, so it never appears in a command line.
[[ $pooler_url =~ $pooler_pattern ]]
db_user=${BASH_REMATCH[1]} db_host=${BASH_REMATCH[2]} db_port=${BASH_REMATCH[3]} db_name=${BASH_REMATCH[4]}
database_url="postgresql://$db_user@$db_host:$db_port/$db_name"
PGPASSFILE=$(mktemp)
export PGPASSFILE
trap 'rm -f "$PGPASSFILE"' EXIT
chmod 600 "$PGPASSFILE"
while true; do
  db_password=$(ask "2/5  Database password" \
"The loupe-demo database password you saved when creating the project. Paste it as is." \
check_nonempty secret verbatim)
  escaped=${db_password//\\/\\\\}
  escaped=${escaped//:/\\:}
  printf '%s:%s:%s:%s:%s\n' "$db_host" "$db_port" "$db_name" "$db_user" "$escaped" > "$PGPASSFILE"
  if psql "$database_url" -qAt -c "select 1" >/dev/null 2>&1; then
    printf '%sConnected to the database.%s\n' "$green" "$reset"
    break
  fi
  printf '%sCould not connect with that password. Try again.%s\n' "$red" "$reset"
done

supabase_url=$(ask "3/5  Supabase project URL" \
"In Supabase: Project Settings (gear icon, bottom left), then Data API.
Copy the Project URL. It looks like https://abcd.supabase.co" \
check_project_url)
# The dashboard also shows the REST endpoint; keep only the scheme and host.
supabase_url=$(printf '%s' "$supabase_url" | sed -E 's|^(https://[^/]+).*|\1|')

service_key=$(ask "4/5  Supabase service_role key" \
"In Supabase: Project Settings, then API Keys. Find service_role (it may say secret),
click Reveal, and copy it. Not the anon or publishable key." \
check_service_key secret)

anthropic_key=$(ask "5/5  Anthropic API key" \
"The loupe-demo key you created in the Claude Console and saved. It starts with sk-ant-" \
check_anthropic_key secret)

echo
# Migrations are not safe to replay, so a ledger outside the public schema records each one
# that finished. A database set up before the ledger existed has to be recorded by hand.
psql "$database_url" -q -v ON_ERROR_STOP=1 >/dev/null <<'SQL'
set client_min_messages = warning;
create schema if not exists loupe_meta;
create table if not exists loupe_meta.migrations (name text primary key, applied_at timestamptz not null default now());
SQL
if [[ $(psql "$database_url" -qAt -c "select to_regclass('public.messages') is not null and not exists (select 1 from loupe_meta.migrations)") == t ]]; then
  echo "${red}This database has tables but no record of which migrations ran.${reset}" >&2
  echo "Insert the name of each applied file into loupe_meta.migrations, then run this again." >&2
  exit 1
fi
echo "==> Applying migrations to the demo database"
for migration in backend/migrations/*.sql; do
  name=$(basename "$migration")
  if [[ $(psql "$database_url" -qAt -v name="$name" <<< "select count(*) from loupe_meta.migrations where name = :'name'") == 1 ]]; then
    continue
  fi
  echo "    $migration"
  if ! psql "$database_url" -q -v ON_ERROR_STOP=1 -f "$migration" >/dev/null 2>&1; then
    echo "${red}Failed on $migration.${reset} Send this message to whoever is helping you." >&2
    exit 1
  fi
  psql "$database_url" -q -v ON_ERROR_STOP=1 -v name="$name" >/dev/null <<< "insert into loupe_meta.migrations (name) values (:'name')"
done

echo "==> Sending settings to the server"
# Shell builtins fill in the file and ssh reads it on stdin, so no secret is an argument.
while IFS= read -r line; do
  case $line in
    ANTHROPIC_API_KEY=*) line="ANTHROPIC_API_KEY=$anthropic_key" ;;
    SUPABASE_URL=*) line="SUPABASE_URL=$supabase_url" ;;
    SUPABASE_SERVICE_KEY=*) line="SUPABASE_SERVICE_KEY=$service_key" ;;
    FRONTEND_ORIGIN=*) line="FRONTEND_ORIGIN=$FRONTEND_ORIGIN" ;;
  esac
  printf '%s\n' "$line"
done < deploy/backend.env.example | ssh -i "$SSH_KEY" "$SERVER" \
  'sudo sh -c '\''set -e
    install -d -m 755 /etc/loupe
    # mktemp creates the file private before any secret is written, then it replaces the old one.
    tmp=$(mktemp /etc/loupe/.backend.env.XXXXXX)
    cat > "$tmp"
    if getent group loupe >/dev/null; then chgrp loupe "$tmp"; chmod 640 "$tmp"; fi
    mv "$tmp" /etc/loupe/backend.env'\'''
echo "${green}${bold}Done.${reset} The database is ready and the server has its settings."
