#!/bin/sh
# by warp3r(2017-2026)
#
# czyszczenie Python Cache
rm -rf `find . -name "__pycache__"`
#
# nadanie uprawnien do zasobow dla odoo
chown -R odoo:odoo .
#
# uprawnienia do plikow i katalogow
chmod 775 $(find . -type d)
chmod 664 $(find . -type f)
#
# aktualizacja repozytorium
git add .
git commit -m "normal commit:: $1"
git push -u origin 15.0
#
chmod +x sprawdz-po-instalacji.py commit.sh
# vim: tabstop=4 softtabstop=0 shiftwidth=4 smarttab expandtab fileformat=unix
#EOF
