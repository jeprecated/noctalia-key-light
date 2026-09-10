{ pkgs, ... }:

{
  packages = [ pkgs.jq pkgs.qt6.qtdeclarative pkgs.quickshell pkgs.python3 ];

  scripts.check.exec = "./scripts/check";
  scripts.install-local.exec = "./scripts/install-local";

  enterTest = ''
    check
  '';
}
