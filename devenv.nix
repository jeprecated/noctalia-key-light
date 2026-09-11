{ pkgs, ... }:

{
  packages = [ pkgs.jq pkgs.qt6.qtdeclarative pkgs.quickshell pkgs.python3 ];

  scripts.check.exec = "./scripts/check";

  enterTest = ''
    check
  '';
}
