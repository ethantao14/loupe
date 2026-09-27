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
ask() {
  local title=$1 where=$2 check=$3 secret=${4:-} value problem
  printf '\n%s%s%s\n%s%s%s\n' "$bold" "$title" "$reset" "$dim" "$where" "$reset" >&2
  while true; do
    if [[ -n "$secret" ]]; then
      read -r -s -p "> (hidden as you paste) " value; echo >&2
    else
      read -r -p "> " value
    fi
    value=$(printf '%s' "$value" | tr -d '[:space:]')
    if problem=$("$check" "$value"); then
      printf '%sOK%s\n' "$green" "$reset" >&2
      printf '%s' "$value"
      return
    fi
    printf '%s%s Try again.%s\n' "$red" "$problem" "$reset" >&2
  done
}

check_pooler() {
  [[ $1 == postgresql://* ]] || { echo "It should start with postgresql://"; return 1; }
  [[ $1 == *pooler.supabase.com* ]] || { echo "That is not the Session pooler string."; return 1; }
  [[ $1 == *"[YOUR-PASSWORD]"* ]] || { echo "Leave [YOUR-PASSWORD] in it; the password is asked next."; return 1; }
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

while true; do
  db_password=$(ask "2/5  Database password" \
"The loupe-demo database password you saved when creating the project. Paste it as is." \
check_nonempty secret)
  # Characters such as ? # / @ in a password break the URI unless percent-encoded.
  encoded=$(DB_PASSWORD="$db_password" python3 -c \
    'import os, urllib.parse; print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))')
  database_url=${pooler_url/\[YOUR-PASSWORD\]/$encoded}
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
echo "==> Applying migrations to the demo database"
for migration in backend/migrations/*.sql; do
  echo "    $migration"
  if ! psql "$database_url" -q -v ON_ERROR_STOP=1 -f "$migration" >/dev/null 2>&1; then
    echo "${red}Failed on $migration.${reset} Send this message to whoever is helping you." >&2
    exit 1
  fi
done

echo "==> Sending settings to the server"
env_file=$(sed \
  -e "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=$anthropic_key|" \
  -e "s|^SUPABASE_URL=.*|SUPABASE_URL=$supabase_url|" \
  -e "s|^SUPABASE_SERVICE_KEY=.*|SUPABASE_SERVICE_KEY=$service_key|" \
  -e "s|^FRONTEND_ORIGIN=.*|FRONTEND_ORIGIN=$FRONTEND_ORIGIN|" \
  deploy/backend.env.example)
# The file goes over ssh on stdin, so no secret appears in a command line.
printf '%s\n' "$env_file" | ssh -i "$SSH_KEY" "$SERVER" \
  'sudo install -d -m 755 /etc/loupe && sudo tee /etc/loupe/backend.env >/dev/null && sudo chmod 600 /etc/loupe/backend.env'
echo "${green}${bold}Done.${reset} The database is ready and the server has its settings."
