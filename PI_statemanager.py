import os
import csv
import XPLMPlugin as plugin
import XPLMPlanes as planes
import XPLMUtilities as utils
import XPLMDataAccess as data
import XPLMMenus as menu
import XPStandardWidgets as swidgets
import XPWidgetDefs as dwidgets

from os import path
from XPPython3 import xp
from mgwidget import MGWidget, MGButton, MGTextBox, get_screen_size


STATES_FOLDER_NAME = 'deck_states'
CONFIG_FILE_NAME = 'statemanager.csv'

XPL_ROOT = utils.XPLMGetSystemPath()
XPL_CONFIG_FILE = path.join(XPL_ROOT, CONFIG_FILE_NAME)

MENU_STATE = 0 # Main plugin menu
MENU_RELOAD = 1 # Menu item to start recording telemetry for a new flight
MENU_SAVE = 2 # Save the current state

MENU_STATE_BASE_REFCON = 100 # States shown in the menu will have refcon set no less than this value

CSV_DELIMITER = ','
CSV_QUOTE_CHAR = '"'
ARRAY_SEPARATOR = ':'


def _read_float_array(dref_id, dref_n):
    out = [0] * dref_n
    data.XPLMGetDatavf(dref_id, out, 0, dref_n)

    return out


def _read_int_array(dref_id, dref_n):
    out = [0] * dref_n
    data.XPLMGetDatavi(dref_id, out, 0, dref_n)

    return out


def _read_byte_array(dref_id, dref_n):
    out = [0] * dref_n
    data.XPLMGetDatab(dref_id, out, 0, dref_n)

    return out


def _read_config_file(path):
    """Read a config file and return its contents.

    Return value:
        A dictionary where keys are datarefs and values are lists `[type, length]`, where
        the "type" is a string representnig the dataref type and "length" is an integer indicating
        the length of the array. A length of 0 indicates a scalar dataref.
    """
    drefs = {}

    if os.path.exists(path):
        with open(path, newline='') as f:
            f_csv = csv.reader(f, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTE_CHAR)

            for record in f_csv:
                dref_name, dref_type = record
                dref_length = 0 # non-array

                if '[' in dref_type:
                    dref_type, dref_length = dref_type.split('[')

                    dref_type += '_array'
                    dref_length = int(dref_length[:-1])

                drefs[dref_name] = [dref_type, dref_length]

    return drefs


def _read_state_file(path, dref_db):
    """Load and return a saved state.

    Arguments:
        path: The full path to the state file.
        dref_db: The dataref database (see `_read_config_file()` for its format)

    Return value:
        A dictionary where keys are datarefs and values the dataref values.
        Arrays are returned as tuples and each value is coerced to the correct type.
    """
    drefs = {}
    dref_type_conversions = {
        'int': int,
        'float': float,
        'double': float,
        'byte_array': lambda x: bytes(map(int, x.split(ARRAY_SEPARATOR))),
        'int_array': lambda x: tuple(map(int, x.split(ARRAY_SEPARATOR))),
        'float_array': lambda x: tuple(map(float, x.split(ARRAY_SEPARATOR)))
    }

    with open(path, newline='') as f:
        f_csv = csv.reader(f, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTE_CHAR)

        for record in f_csv:
            try:
                dref_name, dref_value = record
                dref_type = dref_db[dref_name][0]

                drefs[dref_name] = dref_type_conversions[dref_type](dref_value)
            except Exception:
                print('statemanager: Error deserializing record %s' % record)

                raise

    return drefs


def _write_state_file(path, drefs):
    """Load and return a saved state.

    Arguments:
        path: The full path to the state file.
        drefs: Datarefs in the same format as the one returned by `_read_state_file()`.
    """
    get_type = lambda x: type(x).__name__
    records = []

    for dref_name, dref_value in drefs.items():
        dref_type = get_type(dref_value)

        if dref_type in ('tuple', 'list'):
            dref_type = get_type(dref_value[0])
            dref_value = ARRAY_SEPARATOR.join(str(y) for y in dref_value)
        else:
            dref_value = str(dref_value)

        records.append([dref_name, dref_value])

    with open(path, 'w', newline='') as f:
        f_csv = csv.writer(f, delimiter=CSV_DELIMITER, quotechar=CSV_QUOTE_CHAR)
        f_csv.writerows(records)


class PythonInterface:
    DREF_READ = {
        'int': lambda x, _: data.XPLMGetDatai(x),
        'float': lambda x, _: data.XPLMGetDataf(x),
        'double': lambda x, _: data.XPLMGetDatad(x),
        'int_array': _read_int_array,
        'float_array': _read_float_array,
        'byte_array': _read_byte_array
    }

    DREF_WRITE = {
        'int': lambda x, v: data.XPLMSetDatai(x, v),
        'float': lambda x, v: data.XPLMSetDataf(x, v),
        'double': lambda x, v: data.XPLMSetDatad(x, v),
        'int_array': lambda x, v: data.XPLMSetDatavi(x, v, 0, len(v)),
        'float_array': lambda x, v: data.XPLMSetDatavf(x, v, 0, len(v)),
        'byte_array': lambda x, v: data.XPLMSetDatab(x, v, 0, len(v))
    }

    def __init__(self):
        self.acf_file_path = None
        self.menu_id = None
        self.menu_item_reset_id = None
        self.menu_item_save_id = None
        self.common_drefs = {} # Datarefs from the sim
        self.acf_drefs = {} # Aircraft-specific datarefs
        self.win_save = None

        # List of states shown in the menu.
        # The index is the refcon (- MENU_STATE_BASE_REFCON), the value is the label/file name
        self.menu_state_entries = []

    def XPluginStart(self):
        self.read_sim_config()

        return (
           'StateManager', # Name
           'moongoal.state_manager', # Signature
           'Aircraft state manager' # Description
        )

    def XPluginStop(self):
        if self.win_save:
            self.win_save.destroy()
            self.win_save = None

    def XPluginEnable(self):
        # Register menu
        self.menu_id = xp.createMenu("States", None, MENU_STATE, self._menu_clbk, [])

        # Initialize the plugin
        self.menu_state_entries.clear()
        self.reset_user_aircraft()
        self.add_menu_entries()
        self.create_windows()

        return 1

    def read_sim_config(self):
        self.common_drefs = _read_config_file(XPL_CONFIG_FILE)

        self.init_config_drefs(self.common_drefs)

    def init_config_drefs(self, cfg):
        """Enrich `cfg` by adding the dataref IDs and verify they are writable."""
        to_discard = []

        for name, attrs in cfg.items():
            dref_id = data.XPLMFindDataRef(name)

            if not data.XPLMCanWriteDataRef(dref_id):
                print('State manager: dataref %s is not writable. Discarding it...' % name)
                to_discard.append(name)
            else:
                attrs.append(dref_id)

        for x in to_discard:
            del cfg[x]

    def load_acf_config(self):
        self.acf_drefs = _read_config_file(self.aircraft_config_file)

        self.init_config_drefs(self.acf_drefs)

    def add_menu_entries(self):
        states = self.get_aircraft_state_list()

        if states:
            for s in states:
                self.show_state(s)

            menu.XPLMAppendMenuSeparator(self.menu_id)

        self.menu_item_save_id = xp.appendMenuItem(self.menu_id, "Save current state", MENU_SAVE)
        self.menu_item_reset_id = xp.appendMenuItem(self.menu_id, "Reload state list", MENU_RELOAD)

    def show_state(self, state_name):
        xp.appendMenuItem(self.menu_id, state_name, MENU_STATE_BASE_REFCON + len(self.menu_state_entries))

        self.menu_state_entries.append(state_name)

    def get_aircraft_state_list(self):
        return [x[:-4] for x in os.listdir(self.aircraft_state_folder) if x.endswith('.csv')]

    def reset_menu_entries(self):
        menu.XPLMClearAllMenuItems(self.menu_id)
        self.menu_state_entries.clear()

        self.add_menu_entries()

    def _menu_clbk(self, menu_id, item_id):
        if item_id == MENU_RELOAD:
            print('Reloading aircraft config file & state list...')
            self.load_acf_config()
            self.reset_menu_entries()
        elif item_id == MENU_SAVE:
            self.win_save.is_visible = True
        elif item_id >= MENU_STATE_BASE_REFCON:
            state_idx = item_id - MENU_STATE_BASE_REFCON
            state_name = self.menu_state_entries[state_idx]

            print('Loading aircraft state "%s"...' % state_name)
            self.load_aircraft_state(state_name)

    def save_aircraft_state(self, state_name):
        state_path = self.get_aircraft_state_file(state_name)

        state = {
            dref_name: self.read_dataref(dref_id, dref_type, dref_n)
            for dref_name, (dref_type, dref_n, dref_id) in dict(**self.common_drefs, **self.acf_drefs).items()
        }

        _write_state_file(state_path, state)

    def XPluginDisable(self):
        # Remove menu items
        menu.XPLMDestroyMenu(self.menu_id)

        self.menu_id = None
        self.menu_item_reset_id = None
        self.menu_item_save_id = None
        self.common_drefs.clear()
        self.acf_drefs.clear()
        self.menu_state_entries.clear()

    def XPluginReceiveMessage(self, from_, message, param):
        if message == plugin.XPLM_MSG_PLANE_LOADED and param == planes.XPLM_USER_AIRCRAFT:
            self.reset_user_aircraft()
            self.reset_menu_entries()

    def _create_folders(self):
        if self.aircraft_config_file:
            state_folder = self.aircraft_state_folder

            os.makedirs(state_folder, exist_ok=True)

    def reset_user_aircraft(self):
        """Set the user aircraft's ACF file path, ensure it has the proper folders created and reloads the state list."""
        _, self.acf_file_path = planes.XPLMGetNthAircraftModel(planes.XPLM_USER_AIRCRAFT)

        self._create_folders()
        self.load_acf_config()

    def read_dataref(self, dref_id, dref_type, dref_n):
        return self.DREF_READ[dref_type](dref_id, dref_n)

    def write_dataref(self, dref_id, dref_value, dref_type):
        self.DREF_WRITE[dref_type](dref_id, dref_value)

    def load_aircraft_state(self, state_name):
        drefs = dict(**self.common_drefs, **self.acf_drefs)
        state_path = self.get_aircraft_state_file(state_name)
        state = _read_state_file(state_path, drefs)
        self.apply_state(state)

    def get_aircraft_state_file(self, state_name):
        state_filename = state_name + '.csv'

        return path.join(self.aircraft_state_folder, state_filename)

    def apply_state(self, state):
        drefs = dict(**self.common_drefs, **self.acf_drefs)

        for dref_name, (dref_type, dref_n, dref_id) in drefs.items():
            self.write_dataref(dref_id, state[dref_name], dref_type)

    def create_windows(self):
        self.win_save = SaveStateWindow(self._save_state_clbk)

    def _save_state_clbk(self, state_name):
        print('Saving aircraft state...')

        self.save_aircraft_state(state_name)
        self.load_acf_config()
        self.reset_menu_entries()

        self.win_save.is_visible = False

    @property
    def aircraft_folder(self):
        return path.dirname(self.acf_file_path)

    @property
    def aircraft_state_folder(self):
        return path.join(self.aircraft_folder, STATES_FOLDER_NAME)

    @property
    def aircraft_config_file(self):
        """Plugin specific config file"""
        return path.join(self.aircraft_folder, CONFIG_FILE_NAME)


class SaveStateWindow(MGWidget):
    def __init__(self, save_clbk):
        self.save_clbk = save_clbk

        # Create Window
        scr_width, scr_height = get_screen_size()
        wnd_width = 400
        wnd_height = 75

        super().__init__(
            swidgets.xpWidgetClass_MainWindow,
            "Save state",
            ((scr_width - wnd_width) // 2, (scr_height - wnd_height) // 2, wnd_width, wnd_height),
            props={
                swidgets.xpProperty_MainWindowType: swidgets.xpMainWindowStyle_MainWindow,
                swidgets.xpProperty_MainWindowHasCloseBoxes: 1
            }
        )

        self.add_callback(self._win_callback)

        # Add widgets
        txt_state_name_y = 30
        self.txt_state_name = MGTextBox("", (20, txt_state_name_y, wnd_width - 40), parent=self, max_len=256)

        btn_save_y = txt_state_name_y + MGTextBox.HEIGHT + 5
        btn_save_width = 100
        self.btn_save = MGButton(
            "Save",
            ((wnd_width - btn_save_width) // 2, btn_save_y, btn_save_width),
            parent=self
        )

    def _win_callback(self, message, widget_id, param1, param2):
        if widget_id == self:
            if message == swidgets.xpMessage_CloseButtonPushed:
                self.is_visible = False

                return 1
            elif message == swidgets.xpMsg_PushButtonPressed:
                if param1 == self.btn_save:
                    self.save_clbk(self.txt_state_name.descriptor)

                    return 1
            elif message == dwidgets.xpMsg_Shown:
                if param1 == self:
                    self.txt_state_name.focus = True
                    self.txt_state_name.select_all()

                    return 1

        return 0
