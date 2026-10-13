# Bash completion for the jlmkr alias.
_jlmkr_complete() {
  local cur="${COMP_WORDS[COMP_CWORD]}"
  local commands='create edit exec images list log remove restart shell start startup status stop'
  if (( COMP_CWORD == 1 )); then
    mapfile -t COMPREPLY < <(compgen -W "$commands" -- "$cur")
    return
  fi
  case "${COMP_WORDS[1]:-}" in
    edit|exec|log|remove|restart|shell|start|status|stop)
      if (( COMP_CWORD == 2 )); then
        local item names=()
        for item in "${JLMKR_HOME:-}/jails/"*; do
          [[ -d "$item" ]] && names+=("${item##*/}")
        done
        mapfile -t COMPREPLY < <(compgen -W "${names[*]}" -- "$cur")
      fi
      ;;
  esac
}
complete -F _jlmkr_complete jlmkr
