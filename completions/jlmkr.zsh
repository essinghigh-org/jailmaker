# Zsh completion for the jlmkr alias.
if ! (( $+functions[compdef] )); then
  autoload -Uz compinit
  compinit
fi
_jlmkr_complete() {
  local -a commands jails
  commands=(create edit exec images list log remove restart shell start startup status stop)
  if (( CURRENT == 2 )); then
    _describe -t commands 'Jailmaker command' commands
  elif (( CURRENT == 3 )); then
    case "${words[2]}" in
      edit|exec|log|remove|restart|shell|start|status|stop)
        jails=("${JLMKR_HOME}"/jails/*(N:t))
        (( ${#jails} )) && _describe -t jails 'Jail' jails
        ;;
    esac
  fi
}
compdef _jlmkr_complete jlmkr
