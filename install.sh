#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/essinghigh-org/jailmaker.git"
REF="main"

usage() {
  printf 'Usage: bash install.sh [--ref BRANCH]\n'
}
while (( $# )); do
  case "$1" in
    --ref) [[ $# -ge 2 ]] || { usage >&2; exit 2; }; REF="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done
[[ "$REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && "$REF" != *..* ]] || {
  printf 'Invalid Git branch name.\n' >&2; exit 2;
}

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
[[ -r /dev/tty && -w /dev/tty ]] || die "An interactive terminal is required."
exec 3</dev/tty
for command in midclt git python3; do
  command -v "$command" >/dev/null || die "$command is required."
done
if (( EUID != 0 )); then
  command -v sudo >/dev/null || die "Root or sudo is required."
fi
as_root() {
  if (( EUID == 0 )); then "$@"; else sudo "$@"; fi
}
ask_yes_no() {
  local response
  while :; do
    printf '%s [Y/n] ' "$1" >&2
    IFS= read -r response <&3 || die "Input cancelled."
    case "${response,,}" in
      ""|y|yes) return 0 ;;
      n|no) return 1 ;;
      *) printf 'Please enter y or n.\n' >&2 ;;
    esac
  done
}

printf '\nJailmaker installer\n\n' >&2
pool_json="$(as_root midclt call pool.query)" || die "Unable to query TrueNAS pools."
pool_names="$(printf '%s\n' "$pool_json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    if not isinstance(data, list):
        raise ValueError("not a list")
    for pool in data:
        if pool.get("status") in ("ONLINE", "DEGRADED"):
            name = pool.get("name", "")
            if name and "/" not in name and "\n" not in name:
                print(name)
except (ValueError, TypeError) as e:
    print(f"Invalid pool.query response: {e}", file=sys.stderr)
    sys.exit(1)
')" || die "Cannot parse pool.query response."
mapfile -t pools <<< "$pool_names"
(( ${#pools[@]} > 0 )) && [[ -n "${pools[0]}" ]] || die "No usable pools found."
printf 'Choose a pool (arrow keys or a number, then Enter):\n' >&2
for i in "${!pools[@]}"; do
  printf '  %d. %s\n' "$((i+1))" "${pools[i]}" >&2
done

selected=0
digits=""
while :; do
  printf '\r\033[2KSelected: %d. %s %s' \
    "$((selected+1))" "${pools[selected]}" "${digits:+(number: $digits)}" >&2
  IFS= read -rsn1 key <&3 || die "Input cancelled."
  case "$key" in
    "")
      if [[ -n "$digits" ]]; then
        [[ "$digits" =~ ^[0-9]+$ ]] || die "Invalid number."
        n=$((10#$digits))
        (( n >= 1 && n <= ${#pools[@]} )) || { digits=""; printf '\nInvalid pool number.\n' >&2; continue; }
        selected=$((n-1))
      fi
      break
      ;;
    $'\033')
      IFS= read -rsn2 -t 1 sequence <&3 || sequence=""
      case "$sequence" in
        '[A') selected=$(( (selected+${#pools[@]}-1) % ${#pools[@]} )); digits="" ;;
        '[B') selected=$(( (selected+1) % ${#pools[@]} )); digits="" ;;
      esac
      ;;
    [0-9]) digits+="$key" ;;
    $'\177'|$'\b') digits="${digits%?}" ;;
  esac
done
printf '\nDataset name [jailmaker]: ' >&2
IFS= read -r name <&3 || die "Input cancelled."
name="${name:-jailmaker}"
[[ "$name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ && "$name" != *..* ]] ||
  die "Dataset name must use letters, numbers, underscores, dots or hyphens."
dataset="${pools[selected]}/$name"
destination="/mnt/$dataset"
printf '\nJailmaker will be installed to %s\n' "$destination" >&2
ask_yes_no "Continue?" || { printf 'Cancelled.\n' >&2; exit 0; }

[[ ! -e "$destination" && ! -L "$destination" ]] ||
  die "$destination exists. No changes made."
payload="$(python3 -c 'import json,sys; print(json.dumps({"name":sys.argv[1],"type":"FILESYSTEM"}))' "$dataset")"
printf 'Creating dataset %s...\n' "$dataset" >&2
as_root midclt call pool.dataset.create "$payload" >/dev/null || die "Dataset creation failed."
[[ -d "$destination" ]] || die "Dataset created but $destination is not mounted."
[[ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ]] ||
  die "Mountpoint is not empty. Refusing to clone."

printf 'Cloning Jailmaker (%s)...\n' "$REF" >&2
if ! as_root git clone --depth 1 --branch "$REF" "$REPO" "$destination"; then
  # Only remove our new dataset if the failed clone left it empty.
  if [[ -d "$destination" ]] &&
    [[ -z "$(find "$destination" -mindepth 1 -maxdepth 1 -print -quit)" ]] &&
    as_root midclt call pool.dataset.delete "$dataset" \
      '{"recursive":false,"force":false}' >/dev/null; then
    die "Clone failed; removed the empty dataset."
  fi
  die "Clone failed; retained dataset $dataset for inspection."
fi
as_root chown 0:0 "$destination/jlmkr.py"
as_root chmod +x "$destination/jlmkr.py"
printf '\nInstalled at %s\n' "$destination" >&2

login_user="${SUDO_USER:-$(id -un)}"
entry="$(getent passwd "$login_user")" || die "Unknown account $login_user."
login_home="$(printf '%s' "$entry" | cut -d: -f6)"
login_shell="$(basename "$(printf '%s' "$entry" | cut -d: -f7)")"
if [[ "$login_shell" == bash || "$login_shell" == zsh ]]; then
  if ask_yes_no "Set up $login_shell jlmkr command and shell completions?"; then
    rc="$login_home/.$login_shell"rc
    completion="$destination/completions/jlmkr.$login_shell"
    [[ -f "$completion" ]] || die "Missing $completion."
    if [[ -f "$rc" ]] && grep -Fq '# >>> Jailmaker >>>' "$rc"; then
      printf 'Existing Jailmaker setup found in %s; unchanged.\n' "$rc" >&2
    else
      # A shell function retains its command name for Zsh completion;
      # aliases are expanded before Zsh matches a completion function.
      config="$(
        printf '\n# >>> Jailmaker >>>\n'
        printf 'export JLMKR_HOME=%q\n' "$destination"
        if [[ "$login_user" == root ]]; then
          printf 'jlmkr() { "$JLMKR_HOME/jlmkr.py" "$@"; }\n'
        else
          printf 'jlmkr() { sudo -E "$JLMKR_HOME/jlmkr.py" "$@"; }\n'
        fi
        printf 'source "$JLMKR_HOME/completions/jlmkr.%s"\n' "$login_shell"
        printf '# <<< Jailmaker <<<\n'
      )"
      if (( EUID == 0 )) && [[ "$login_user" != root ]]; then
        printf '%s\n' "$config" | sudo -u "$login_user" tee -a "$rc" >/dev/null
      else
        printf '%s\n' "$config" >> "$rc"
      fi
      printf 'Added jlmkr alias and completions to %s.\n' "$rc" >&2
    fi
  fi
else
  printf 'Shell alias/completion is only supported for bash/zsh (%s detected).\n' "$login_shell" >&2
fi
printf '\nInstallation complete. Start a new shell to use the alias.\n' >&2
