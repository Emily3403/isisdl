from asyncio import get_event_loop

from urwid import MainLoop, AsyncioEventLoop, Widget, Text, Filler, AttrWrap, LineBox, Columns, Frame


def top_selector() -> Widget:
    t1 = AttrWrap(Text("isisdl", align="left"), "bg")
    t2 = AttrWrap(Text("settings", align="left"), "bg")
    t3 = AttrWrap(Text("compression", align="left"), "bg")
    t4 = AttrWrap(Text("sync database", align="left"), "bg")

    t9 = AttrWrap(Text("help", align="left"), "bg")
    t10 = AttrWrap(Text("exit", align="left"), "bg")

    mk = lambda it: (len(it.text), it)

    return Columns([
        ("weight", 3, Columns([mk(t1), mk(t2), mk(t3), mk(t4), ], dividechars=2)),
        ("weight", 0.2, Columns([mk(t9), mk(t10)], dividechars=2)),
    ])


def left_box() -> Widget:
    return LineBox(Filler(AttrWrap(Text("Left Box"), "normal", ), "top"))


def right_box() -> Widget:
    return LineBox(Filler(AttrWrap(Text("Right Box"), "normal", ), "top"))


def main_widget() -> Widget:
    header = top_selector()
    left = left_box()
    right = right_box()

    cols = Columns([left, ("weight", 3, right)])

    return Frame(body=cols, header=header)


def create_main_loop() -> MainLoop:
    palette = [
        ("bg", "black", "light gray"),
    ]

    return MainLoop(main_widget(), palette=palette, event_loop=AsyncioEventLoop(loop=get_event_loop()))


def main_with_new_ui() -> None:
    """
    This function is the main entry point for the new UI.
    It will run the `_new_main` function in the background and then start the UI.
    """
    from isisdl.__main__ import _new_main

    get_event_loop().create_task(_new_main())

    main = create_main_loop()
    main.run()
