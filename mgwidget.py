import XPWidgets as widgets
import XPWidgetDefs as wdefs
import XPStandardWidgets as swidgets
import XPLMDataAccess as data

class MGWidget:
    @property
    def parent(self):
        return widgets.XPGetParentWidget(self.id)

    @parent.setter
    def parent(self, value):
        widgets.XPPlaceWidgetWithin(self.id, value.id)

    @property
    def is_root(self):
        return self.parent is None

    @property
    def children_count(self):
        return widgets.XPCountChildWidgets(self.id)

    @property
    def is_visible(self):
        return widgets.XPIsWidgetVisible(self.id)

    @is_visible.setter
    def is_visible(self, value):
        if value:
            widgets.XPShowWidget(self.id)
        else:
            widgets.XPHideWidget(self.id)

    @property
    def root(self):
        return widgets.XPFindRootWidget(self.id)

    @property
    def is_front(self):
        return widgets.XPIsWidgetInFront(self.id)

    @property
    def geometry(self):
        left, top, right, bottom = widgets.XPGetWidgetGeometry(self.id)

        geom = xp_to_geom(left, top, right, bottom)

        if self.parent:
            geom = parent_to_screen(geom, self.parent.geometry)

        return geom

    @geometry.setter
    def geometry(self, value):
        widgets.XPSetWidgetGeometry(self.id, geom_to_xp(*value))

    @property
    def descriptor(self):
        return widgets.XPGetWidgetDescriptor(self.id)

    @descriptor.setter
    def descriptor(self, value):
        widgets.XPSetWidgetDescriptor(self.id, value)

    @property
    def window(self):
        return widgets.XPGetWidgetUnderlyingWindow(self.id)

    @property
    def focus(self):
        return widgets.XPGetWidgetWithFocus() == self.id

    @focus.setter
    def focus(self, value):
        if value:
            widgets.XPSetKeyboardFocus(self.id)
        else:
            widgets.XPLoseKeyboardFocus(self.id)

    def __init__(self, *args, **kwargs):
        n_pos_args = len(args)

        if n_pos_args == 3:
            ctor = self.__init_create
        elif n_pos_args == 1:
            ctor = self.__init_id
        else:
            raise TypeError('Invalid number of positional arguments. Must be 3 or 1.')

        ctor(*args, **kwargs)

    def __init_id(self, widget_id):
        self.id = widget_id

    def __init_create(self, class_, descriptor, geometry, parent=None, props=None, visible=False):
        if parent:
            geometry = screen_to_parent(geometry, parent.geometry)

        self.id = widgets.XPCreateWidget(*geom_to_xp(*geometry), visible, descriptor, parent is None, parent.id if parent else 0, class_)

        if not self.id:
            raise RuntimeError('Widget %s creation failed' % descriptor)

        if props:
            for name, value in props.items():
                self.set_property(name, value)

    def __del__(self):
        self.destroy()

    def destroy(self):
        if self.id:
            widgets.XPDestroyWidget(self.id, 1)

            self.id = None

    def send_message(self, message, param1=None, param2=None, dispatch_mode=wdefs.xpMode_UpChain):
        return widgets.XPSendMessageToWidget(self.id, message, dispatch_mode, param1, param2)

    def bring_root_to_front(self):
        widgets.XPBringRootWidgetToFront(self.id)

    def get_property(self, prop_id):
        return widgets.XPGetWidgetProperty(self.id, prop_id)

    def property_exists(self, prop_id):
        exists = []

        widgets.XPGetWidgetProperty(self.id, prop_id, exists)

        return exists[0]

    def set_property(self, prop_id, prop_value):
        widgets.XPSetWidgetProperty(self.id, prop_id, prop_value)

    def add_callback(self, clbk):
        widgets.XPAddWidgetCallback(self.id, clbk)

    @classmethod
    def from_widget_id(cls, widget_id):
        return cls(widget_id)

    @classmethod
    def get_widget_for_location(cls, container, x, y, recursive=False, visible_only=True):
        out = widgets.XPGetWidgetForLocation(container.id, x, y, recursive, visible_only)

        return cls.from_widget_id(out) if out else None

    def __eq__(self, o: object) -> bool:
        return self.id == (o.id if isinstance(o, type(self)) else o)


class MGTextBox(MGWidget):
    HEIGHT = 15

    def __init__(self, text, geometry, parent, visible=True, max_len=0):
        """Text box.

        Arguments:
            text: The initial text
            geometry: Tuple (left, top, width)
            parent: The parent MGWidget
            visible: True to show, False to hide
            max_len: Maximum number of characters (0 to disable)
        """
        super().__init__(
            swidgets.xpWidgetClass_TextField,
            text,
            geometry + (self.HEIGHT,),
            parent=parent,
            props={
                swidgets.xpProperty_TextFieldType: swidgets.xpTextEntryField,
                swidgets.xpProperty_MaxCharacters: max_len
            },
            visible=visible
        )

    def select_all(self):
        self.select_text(0, len(self.descriptor))

    def deselect_text(self):
        self.select_text(0, 0)

    def select_text(self, from_, to):
        self.set_property(swidgets.xpProperty_EditFieldSelStart, from_)
        self.set_property(swidgets.xpProperty_EditFieldSelEnd, to)


class MGButton(MGWidget):
    HEIGHT = 15

    def __init__(self, text, geometry, parent, visible=True):
        """Pushbutton.

        Arguments:
            text: The button's label text
            geometry: Tuple (left, top, width)
            parent: The parent MGWidget
            visible: True to show, False to hide
        """
        super().__init__(
            swidgets.xpWidgetClass_Button,
            text,
            geometry + (self.HEIGHT,),
            parent=parent,
            props={
                swidgets.xpProperty_ButtonType: swidgets.xpPushButton,
                swidgets.xpProperty_ButtonBehavior: swidgets.xpButtonBehaviorPushButton
            },
            visible=visible
        )


def xp_to_geom(left, top, right, bottom):
    wnd_height = get_screen_height()

    return left, wnd_height - top, right - left, top - bottom


def geom_to_xp(left, top, width, height):
    wnd_height = get_screen_height()
    inverted_top = wnd_height - top

    return left, inverted_top, left + width, inverted_top - height


def screen_to_parent(geom, parent_geom):
    return (
        geom[0] + parent_geom[0],
        geom[1] + parent_geom[1],
        geom[2],
        geom[3]
    )


def parent_to_screen(geom, parent_geom):
    return (
        geom[0] - parent_geom[0],
        geom[1] - parent_geom[1],
        geom[2],
        geom[3]
    )


def get_screen_size():
    return get_screen_width(), get_screen_height()


def get_screen_width():
    if not hasattr(get_screen_width, 'DREF'):
        get_screen_width.DREF = data.XPLMFindDataRef('sim/graphics/view/window_width')

    return data.XPLMGetDatai(get_screen_width.DREF)


def get_screen_height():
    if not hasattr(get_screen_height, 'DREF'):
        get_screen_height.DREF = data.XPLMFindDataRef('sim/graphics/view/window_height')

    return data.XPLMGetDatai(get_screen_height.DREF)
