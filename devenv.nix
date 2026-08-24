{ pkgs, ... }:

{
  packages = [ pkgs.jq pkgs.qt6.qtdeclarative ];

  scripts.check.exec = "./scripts/check";
  scripts.install-local.exec = "./scripts/install-local";

  enterTest = ''
    check
  '';
}
