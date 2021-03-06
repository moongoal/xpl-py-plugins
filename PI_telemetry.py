import math
import time
import os
import datetime as dt
import XPLMPlugin as plugin
import XPLMPlanes as planes
import XPLMUtilities as utils
import XPLMProcessing as proc
import XPLMDataAccess as data
import XPLMMenus as menu

from XPPython3 import xp
from os import path


DTYPE_INT = object()
DTYPE_FLOAT = object()
DTYPE_DOUBLE = object()
DTYPE_INT_ARRAY = object()
DTYPE_FLOAT_ARRAY = object()
DTYPE_BYTES = object()

N_ENGINES = object()

XPL_ROOT = utils.XPLMGetSystemPath()
XPL_FOLDER_OUTPUT = path.join(XPL_ROOT, 'Output')
XPL_FOLDER_TELEMETRY = path.join(XPL_FOLDER_OUTPUT, 'telemetry')

LABEL_GS = 'gs'
LABEL_HEIGHT = 'height'

MENU_TELEMETRY = 0 # Main plugin menu
MENU_RESET = 1 # Menu item to start recording telemetry for a new flight


def m_to_ft(m):
    return m * 3.28084

def ms_to_kts(ms):
    return ms * 1.943844

def _read_float_array(dref_id, dref_n):
    out = [0] * dref_n
    data.XPLMGetDatavf(dref_id, out, 0, dref_n)

    return ':'.join([str(x) for x in out])


def _get_airplane_icao(acf_path):
    with open(acf_path) as f:
        for line in f:
            line = line.strip()

            if line.startswith('P acf/_ICAO'):
                rec_type, prop_name, prop_value = line.split(' ', 2)

                return prop_value


class PythonInterface:
    RECORD_INTERVAL = 5 # seconds - will be halved during t/o and ldg
    MAX_BUF_SIZE = 128 # elements

    FRAME_CONTENTS = [
        # Flight model
        ('sim/flightmodel/position/latitude', DTYPE_DOUBLE, 'latitude', None),
        ('sim/flightmodel/position/longitude', DTYPE_DOUBLE, 'longitude', None),
        ('sim/flightmodel/position/elevation', DTYPE_DOUBLE, 'altitude', None),
        ('sim/flightmodel/position/y_agl', DTYPE_FLOAT, LABEL_HEIGHT, None),
        ('sim/flightmodel/position/groundspeed', DTYPE_FLOAT, LABEL_GS, None),
        ('sim/flightmodel/position/indicated_airspeed', DTYPE_FLOAT, 'ias', None),
        ('sim/flightmodel/position/true_psi', DTYPE_FLOAT, 'true_hdg', None),
        ('sim/flightmodel/engine/ENGN_FF_', DTYPE_FLOAT_ARRAY, 'ff', N_ENGINES),
        ('sim/flightmodel2/engines/throttle_used_ratio', DTYPE_FLOAT_ARRAY, 'true_throttle', N_ENGINES),
        ('sim/flightmodel/weight/m_fuel_total', DTYPE_FLOAT, 'fuel', None),
        ('sim/flightmodel/weight/m_total', DTYPE_FLOAT, 'weight', None),
        ('sim/flightmodel2/engines/AoA_angle_degrees', DTYPE_FLOAT, 'aoa', None),
        ('sim/flightmodel/position/theta', DTYPE_FLOAT, 'pitch', None),
        ('sim/flightmodel/position/phi', DTYPE_FLOAT, 'roll', None),
        ('sim/flightmodel/position/psi', DTYPE_FLOAT, 'yaw', None),
        ('sim/flightmodel/position/true_theta', DTYPE_FLOAT, 'pitch_terr', None),
        ('sim/flightmodel/position/true_phi', DTYPE_FLOAT, 'roll_terr', None),
        ('sim/flightmodel/misc/machno', DTYPE_FLOAT, 'mach_no', None),
        ('sim/flightmodel/controls/elv_trim', DTYPE_FLOAT, 'elev_trim', None),
        ('sim/flightmodel/controls/flaprat', DTYPE_FLOAT, 'flap1_ratio', None),
        ('sim/flightmodel/controls/flap2rat', DTYPE_FLOAT, 'flap2_ratio', None),
        ('sim/flightmodel/controls/speedbrake_ratio', DTYPE_FLOAT, 'speed_brake', None),

        # Weather
        ('sim/weather/rain_percent', DTYPE_FLOAT, 'rain_percent', None),
        ('sim/weather/thunderstorm_percent', DTYPE_FLOAT, 'thunderstorm_percent', None),
        ('sim/weather/wind_turbulence_percent', DTYPE_FLOAT, 'wind_turbulence_percent', None),
        ('sim/weather/wind_direction_degt', DTYPE_FLOAT, 'wind_direction', None),
        ('sim/weather/wind_speed_kt', DTYPE_FLOAT, 'wind_speed', None),
        ('sim/weather/barometer_current_inhg', DTYPE_FLOAT, 'pressure', None),
        # ('sim/weather/runway_friction', DTYPE_INT, 'rwy_friction', None),
        # ('sim/weather/runway_is_patchy', DTYPE_INT, 'rwy_patchy', None),

        # Aircraft configuration
        ('sim/cockpit/switches/auto_brake_settings', DTYPE_INT, 'auto_brake', None),
    ] # Set of datarefs making up each telemetry frame

    DREF_READ = {
        DTYPE_INT: data.XPLMGetDatai,
        DTYPE_FLOAT: data.XPLMGetDataf,
        DTYPE_DOUBLE: data.XPLMGetDatad,
        DTYPE_FLOAT_ARRAY: _read_float_array
    } # dataref read dispatch table

    AIRCRAFT_ICAO_PLACEHOLDER = 'ZZZZ'

    def __init__(self):
        self.name = "Telemetry"
        self.sig = "moongoal.telemetry"
        self.desc = "Aircraft telemetry recorder"

        self.buffer = [] # Telemetry buffer
        self.drefs = [] # Tuples of (dataref_id, type, n_elements) making up the telemetry frame
        self.header = [] # List of strings that will make up the header of the file. Must be empty here.
        self.clean_file = True # True if the file was never written to
        self.num_engines = 8 # 8 is the max number of available engine slots
        self.aircraft_icao = self.AIRCRAFT_ICAO_PLACEHOLDER
        self.acf_file_path = None
        self.telemetry_file_path = None
        self.file = None
        self.gs_index = None # Index of gs in frame data
        self.h_index = None # Index of height in frame data
        self.cur_gs = 0
        self.cur_height = 0
        self.menu_id = None
        self.menu_item_reset_id = None

        self._create_folders()

    def XPluginStart(self):
        return self.name, self.sig, self.desc

    def XPluginStop(self):
        pass

    def XPluginEnable(self):
        proc.XPLMRegisterFlightLoopCallback(self.flight_loop_clbk, self.RECORD_INTERVAL, None)

        # Register menu
        self.menu_id = xp.createMenu("Telemetry", None, MENU_TELEMETRY, self._menu_clbk, [])
        self.menu_item_reset_id = xp.appendMenuItem(self.menu_id, "Record new flight", MENU_RESET)

        self.init_telemetry()

        return 1

    def _menu_clbk(self, menu_id, item_id):
        if item_id == MENU_RESET:
            print('New telemetry log manually initiated')

            self.close_output_file()
            self.init_telemetry()

    def init_telemetry(self):
        """Initialize telemetry for a new plane."""
        try:
            self.aircraft_icao, self.acf_file_path = self.get_user_aircraft()

            if self.is_aircraft_loaded:
                self.num_engines = data.XPLMGetDatai(
                    data.XPLMFindDataRef('sim/aircraft/engine/acf_num_engines')
                )

                self.init_drefs() # This must happen after num_engines is retrieved
                self.open_output_file() # This must happen after init_drefs()
        except Exception as exc:
            # This can happen if the ACF file is still begin read during initialization.
            # During the next flight model frame, a new attempt will be made
            print('Error during telemetry initialisation - telemetry will be initialized as part of the next flight model frame')
            print(exc)

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
        elif message == plugin.XPLM_MSG_AIRPORT_LOADED:
            self.init_telemetry()
        elif message == plugin.XPLM_MSG_LIVERY_LOADED and param == planes.XPLM_USER_AIRCRAFT:
            self.open_output_file() # Plane is the same, no need to initialize telemetry again
        elif message == plugin.XPLM_MSG_PLANE_UNLOADED and param == planes.XPLM_USER_AIRCRAFT:
            self.close_output_file()
        elif message == plugin.XPLM_MSG_PLANE_CRASHED:
            self.close_output_file(crash=True)

    def new_telemetry_file_path(self):
        self.telemetry_file_path = path.join(XPL_FOLDER_TELEMETRY, '{icao}-{date}.csv'.format(
            icao=self.aircraft_icao,
            date=dt.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
        ))
        self.clean_file = True

    def _create_folders(self):
        if not path.exists(XPL_FOLDER_TELEMETRY):
            os.makedirs(XPL_FOLDER_TELEMETRY, exist_ok=True)

    def get_user_aircraft(self):
        """Return the user aircraft's ICAO code and ACF file path."""
        out_file, out_path = planes.XPLMGetNthAircraftModel(planes.XPLM_USER_AIRCRAFT)

        acf_icao = _get_airplane_icao(out_path) if out_file else self.AIRCRAFT_ICAO_PLACEHOLDER

        return acf_icao, out_path

    def flight_loop_clbk(self, since_last_call, since_last_fl, counter, _):
        if not self.file:
            self.init_telemetry()

        self.record_frame()

        # Compute new record interval
        record_interval = self.RECORD_INTERVAL

        if self.cur_gs > 25 and self.cur_height < 2000: # Increase resolution upon take-off/landing
            record_interval = math.floor(float(record_interval) / 2)

        return max(1, record_interval)

    def open_output_file(self):
        if self.aircraft_icao == self.AIRCRAFT_ICAO_PLACEHOLDER:
            return

        if not self.clean_file or not self.file:
            self.new_telemetry_file_path()

        if self.file:
            self.file.close()

        self.file = open(self.telemetry_file_path, 'w')

        print(','.join(self.header), file=self.file)

    def close_output_file(self, *, crash=False):
        if self.file:
            self.flush_buffer()

            if crash:
                print('CRASH', file=self.file)

            self.file.close()
            self.clean_file = True
            self.file = None

    def record_frame(self):
        """Record one telemetry frame."""
        frame = self.get_frame()

        self.cur_height = m_to_ft(frame[self.h_index])
        self.cur_gs = ms_to_kts(abs(frame[self.gs_index]))

        self.buffer.append(frame)

        if len(self.buffer) >= self.MAX_BUF_SIZE:
            self.flush_buffer()

    def get_frame(self):
        return [time.time()] + [self.read_dataref(dref_id, dref_type, dref_n) for dref_id, dref_type, dref_n in self.drefs]

    def read_dataref(self, dref_id, dref_type, dref_n):
        params = [dref_id]

        if dref_n:
            params.append(dref_n)

        return self.DREF_READ[dref_type](*params)

    def init_drefs(self):
        self.drefs.clear()
        self.header.clear()

        self.header.append('t')

        for dref_name, dref_type, dref_label, dref_n in self.FRAME_CONTENTS:
            dref_id = data.XPLMFindDataRef(dref_name)

            if dref_n is N_ENGINES:
                dref_n = self.num_engines

            if dref_id is not None:
                self.drefs.append((dref_id, dref_type, dref_n))
                self.header.append(dref_label)

                if dref_label == LABEL_GS:
                    self.gs_index = len(self.drefs) - 1
                elif dref_label == LABEL_HEIGHT:
                    self.h_index = len(self.drefs) - 1

    def flush_buffer(self):
        if self.buffer:
            for frame in self.buffer:
                print(','.join([str(x) for x in frame]), file=self.file)

            self.file.flush()
            self.buffer.clear()
            self.clean_file = False

    @property
    def aircraft_folder(self):
        return path.dirname(self.acf_file_path)

    @property
    def is_aircraft_loaded(self):
        return self.aircraft_icao != self.AIRCRAFT_ICAO_PLACEHOLDER
