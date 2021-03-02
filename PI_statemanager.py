import os
import XPLMPlugin as plugin
import XPLMPlanes as planes
import XPLMUtilities as utils
import XPLMProcessing as proc
import XPLMDataAccess as data
import XPLMMenus as menu

from XPPython3 import xp
from os import path


XPL_ROOT = utils.XPLMGetSystemPath()
STATES_FOLDER_NAME = 'deck_states'

MENU_TELEMETRY = 0 # Main plugin menu
MENU_RELOAD = 1 # Menu item to start recording telemetry for a new flight


def _read_float_array(dref_id, dref_n):
    out = [0] * dref_n
    data.XPLMGetDatavf(dref_id, out, 0, dref_n)

    return ':'.join([str(x) for x in out])


class PythonInterface:
    DREF_READ = {
    }

    def __init__(self):
        self.drefs = [] # Tuples of (dataref_id, type, n_elements) making up the telemetry frame
        self.acf_file_path = None
        self.menu_id = None
        self.menu_item_reset_id = None

    def XPluginStart(self):
        return (
           'StateManager', # Name
           'moongoal.state_manager', # Signature
           'Aircraft state manager' # Description
        )

    def XPluginStop(self):
        pass

    def XPluginEnable(self):
        # Register menu
        self.menu_id = xp.createMenu("States", None, MENU_TELEMETRY, self._menu_clbk, [])

        self.add_menu_entries()

        return 1

    def add_menu_entries(self):
        self.menu_item_reset_id = xp.appendMenuItem(self.menu_id, "Reload states", MENU_RELOAD)
    
    def reset_menu_entries(self):
        # TODO: remove menu entries
        self.add_menu_entries()

    def _menu_clbk(self, menu_id, item_id):
        if item_id == MENU_RELOAD:
            self.close_output_file()
            self.init_telemetry()

    def XPluginDisable(self):
        proc.XPLMUnregisterFlightLoopCallback(self.flight_loop_clbk, None)
        self.close_output_file()

        # Remove menu items
        menu.XPLMDestroyMenu(self.menu_id)

        self.menu_id = None
        self.menu_item_reset_id = None

    def XPluginReceiveMessage(self, from_, message, param):
        if message == plugin.XPLM_MSG_PLANE_LOADED and param == planes.XPLM_USER_AIRCRAFT:
            self.init_telemetry()
        elif message == plugin.XPLM_MSG_PLANE_UNLOADED and param == planes.XPLM_USER_AIRCRAFT:
            self.close_output_file()

    def _create_folders(self):
        if not path.exists(XPL_FOLDER_TELEMETRY):
            os.makedirs(XPL_FOLDER_TELEMETRY, exist_ok=True)

    def get_user_aircraft(self):
        """Return the user aircraft's ICAO code and ACF file path."""
        out_file, out_path = planes.XPLMGetNthAircraftModel(planes.XPLM_USER_AIRCRAFT)
        acf_icao = _get_airplane_icao(out_path)

        return acf_icao, out_path

    def read_dataref(self, dref_id, dref_type, dref_n):
        return self.DREF_READ[dref_type](dref_id, dref_n)

    @property
    def aircraft_folder(self):
        return path.dirname(self.acf_file_path)
