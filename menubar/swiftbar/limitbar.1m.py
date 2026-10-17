#!/opt/homebrew/bin/python3
# <xbar.title>LimitBar</xbar.title>
# <xbar.desc>Límites de uso de mis IAs</xbar.desc>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
# <swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
# <swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
# <swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
# SwiftBar lo ejecuta cada minuto (lo dice el «.1m» del nombre). Solo lee el fichero local.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from menubar.render import main  # noqa: E402

main()
