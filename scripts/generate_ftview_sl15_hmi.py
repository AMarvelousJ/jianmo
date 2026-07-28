"""Generate FactoryTalk View SE 10 graphic XML for the SL15 HIL monitor.

The generated displays intentionally contain no PLC write actions. They bind only
to the controller-scoped SL15_HIL_* feedback tags through the existing plc_sl
FactoryTalk Linx shortcut.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "hmi" / "factorytalk-view-se"
SCHEMA_NAME = "Gfx-SE11.xsd"
SHORTCUT = "plc_sl"


def attrs(**values: object) -> dict[str, str]:
    return {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in values.items()}


BASE_OBJECT = attrs(
    visible=True,
    wallpaper=False,
    toolTipText="",
    exposeToVba="notExposed",
    isReferenceObject=False,
)


def tag(name: str) -> str:
    return f"{{[{SHORTCUT}]{name}}}"


def add_rect(
    root: ET.Element,
    name: str,
    x: int,
    y: int,
    width: int,
    height: int,
    fill: str,
    line: str = "#2A3C4E",
    line_width: int = 1,
) -> ET.Element:
    return ET.SubElement(
        root,
        "rectangle",
        attrs(
            name=name,
            height=height,
            width=width,
            left=x,
            top=y,
            **BASE_OBJECT,
            backStyle="solid",
            backColor=fill,
            foreColor=line,
            lineStyle="solid",
            lineWidth=line_width,
            patternStyle="none",
            patternColor=line,
            endColor=fill,
            gradientStop=50,
            gradientDirection="gradientDirectionHorizontal",
            gradientShadingStyle="gradientHorizontalFromRight",
        ),
    )


def add_text(
    root: ET.Element,
    name: str,
    caption: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    color: str = "#DDE7F0",
    size: int = 18,
    bold: bool = False,
    align: str = "middleLeft",
    fill: str = "#FFFFFF",
    transparent: bool = True,
) -> ET.Element:
    return ET.SubElement(
        root,
        "text",
        attrs(
            name=name,
            height=height,
            width=width,
            left=x,
            top=y,
            **BASE_OBJECT,
            backStyle="transparent" if transparent else "solid",
            backColor=fill,
            foreColor=color,
            wordWrap=True,
            sizeToFit=False,
            alignment=align,
            fontFamily="Microsoft YaHei UI",
            fontSize=size,
            bold=bold,
            italic=False,
            underline=False,
            strikethrough=False,
            caption=caption,
        ),
    )


def add_numeric(
    root: ET.Element,
    name: str,
    expression: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    decimals: int = 2,
    field_length: int = 10,
    size: int = 24,
    fill: str = "#111A24",
    color: str = "#F4F8FB",
) -> ET.Element:
    elem = ET.SubElement(
        root,
        "numericDisplay",
        attrs(
            name=name,
            height=height,
            width=width,
            left=x,
            top=y,
            **BASE_OBJECT,
            backColor=fill,
            backStyle="solid",
            foreColor=color,
            fontFamily="Microsoft YaHei UI",
            fontSize=size,
            bold=True,
            italic=False,
            underline=False,
            strikethrough=False,
            justification="center",
            fieldLength=field_length,
            showDigitGrouping=False,
            decimalPlaces=decimals,
            format="floatingPoint",
            overflow="fillWithAsterisks",
            leadingCharacter="blanks",
            decimalPlaceType="fixed",
        ),
    )
    connections = ET.SubElement(elem, "connections")
    ET.SubElement(connections, "connection", attrs(name="值", expression=expression))
    return elem


def add_bool_indicator(
    root: ET.Element,
    name: str,
    expression: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    off_caption: str,
    on_caption: str,
    off_color: str = "#7A2932",
    on_color: str = "#17845C",
) -> ET.Element:
    elem = ET.SubElement(
        root,
        "multistateIndicator",
        attrs(
            name=name,
            height=height,
            width=width,
            left=x,
            top=y,
            **BASE_OBJECT,
            backStyle="solid",
            borderStyle="line",
            borderUsesBackColor=False,
            borderWidth=2,
            captionOnBorder=False,
            description="",
            shape="rectangle",
            triggerType="value",
        ),
    )
    states = ET.SubElement(elem, "states")
    for state_id, value, caption, back_color in (
        (0, 0, off_caption, off_color),
        (1, 1, on_caption, on_color),
    ):
        state = ET.SubElement(
            states,
            "state",
            attrs(
                stateId=state_id,
                value=value,
                patternStyle="none",
                patternColor=back_color,
                endColor=back_color,
                gradientStop=50,
                gradientDirection="gradientDirectionHorizontal",
                gradientShadingStyle="gradientHorizontalFromRight",
                backColor=back_color,
                blink=False,
                borderColor="#31465A",
            ),
        )
        ET.SubElement(
            state,
            "caption",
            attrs(
                backStyle="transparent",
                backColor=back_color,
                fontFamily="Microsoft YaHei UI",
                fontSize=18,
                bold=True,
                italic=False,
                underline=False,
                strikethrough=False,
                caption=caption,
                alignment="middleCenter",
                blink=False,
                color="#FFFFFF",
                wordWrap=True,
            ),
        )
    connections = ET.SubElement(elem, "connections")
    ET.SubElement(connections, "connection", attrs(name="指示器", expression=expression))
    return elem


def add_button(
    root: ET.Element,
    name: str,
    caption: str,
    command: str,
    x: int,
    y: int,
    width: int,
    height: int,
    tab_index: int,
    *,
    active: bool = False,
) -> ET.Element:
    fill = "#2878B8" if active else "#23384B"
    elem = ET.SubElement(
        root,
        "button",
        attrs(
            name=name,
            height=height,
            width=width,
            left=x,
            top=y,
            **BASE_OBJECT,
            style="beveled",
            bevelWidth=2,
            captureCursor=False,
            highlightOnFocus=True,
            tabIndex=tab_index,
        ),
    )
    ET.SubElement(elem, "command", attrs(pressAction=command, repeatAction="", releaseAction="", repeatRate=0.25))
    up = ET.SubElement(
        elem,
        "up",
        attrs(
            patternColor=fill,
            patternStyle="none",
            backColor=fill,
            backStyle="solid",
            foreColor="#FFFFFF",
            endColor=fill,
            gradientStop=50,
            gradientDirection="gradientDirectionHorizontal",
            gradientShadingStyle="gradientHorizontalFromRight",
        ),
    )
    ET.SubElement(
        up,
        "caption",
        attrs(
            fontFamily="Microsoft YaHei UI",
            fontSize=17,
            bold=True,
            italic=False,
            underline=False,
            strikethrough=False,
            caption=caption,
        ),
    )
    ET.SubElement(up, "imageSettings", attrs(imageReference="noImage"))
    down = ET.SubElement(
        elem,
        "down",
        attrs(
            downSameAsUp=True,
            patternColor="#111A24",
            patternStyle="none",
            backColor="#111A24",
            backStyle="solid",
            foreColor="#FFFFFF",
            endColor="#111A24",
            gradientStop=50,
            gradientDirection="gradientDirectionHorizontal",
            gradientShadingStyle="gradientHorizontalFromRight",
        ),
    )
    ET.SubElement(
        down,
        "caption",
        attrs(
            fontFamily="Microsoft YaHei UI",
            fontSize=17,
            bold=True,
            italic=False,
            underline=False,
            strikethrough=False,
            caption="",
        ),
    )
    ET.SubElement(down, "imageSettings", attrs(imageReference="noImage"))
    ET.SubElement(
        elem,
        "ability",
        attrs(
            showDisabledState=False,
            expression="",
            enabledWhenExpressionIsTrue=True,
            disabledImageType="useGrayscale",
        ),
    )
    confirm = ET.SubElement(
        elem,
        "confirm",
        attrs(
            confirmAction=False,
            buttonSetting="okCancel",
            titleBar=True,
            titleBarText="确认",
            windowPosition="Centered of screen",
        ),
    )
    ET.SubElement(
        confirm,
        "caption",
        attrs(
            fontFamily="Microsoft YaHei UI",
            fontSize=10,
            bold=False,
            italic=False,
            underline=False,
            strikethrough=False,
            caption="是否确定要执行此操作?",
        ),
    )
    ET.SubElement(confirm, "imageSettings", attrs(imageReference="noImage"))
    return elem


def make_root() -> ET.Element:
    root = ET.Element(
        "gfx",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": SCHEMA_NAME,
        },
    )
    ET.SubElement(
        root,
        "displaySettings",
        attrs(
            displayType="replace",
            position="specifyPositionInPixels",
            positionX=0,
            positionY=0,
            securityCode="*",
            backColor="#0B1118",
            titleBar=False,
            maximumTagUpdateRate=0.25,
            focusHighlightColor="#33A8FF",
            disableFocusHighlight=False,
            size="specifySizeInPixels",
            width=1920,
            height=1080,
            allowMultipleRunningCopies=False,
            cacheAfterDisplaying=True,
            sizeToMainWindow=False,
            showLastAcquiredValue=True,
            TrackScreenForNavigation=True,
            TrackName="SL15",
            allowResizing=True,
            whenResized="scale",
            beepOnPress=False,
            highlightWhenCursorPassesOver=True,
            interactiveHighlightColor="#33A8FF",
            displayOnScreenKeyboard=False,
            allowButtonActionOnError=False,
            fieldNotSelectedTextColor="#F4F8FB",
            fieldNotSelectedFillColor="#111A24",
            fieldSelectedTextColor="#FFFFFF",
            fieldSelectedFillColor="#2878B8",
            fieldInErrorNotSelectedTextColor="#FFFFFF",
            fieldInErrorNotSelectedFillColor="#C83B46",
            fieldInErrorSelectedTextColor="#FFFFFF",
            fieldInErrorSelectedFillColor="#C83B46",
            startupCommand="",
            shutdownCommand="",
            useGradientStyle=False,
            endColor="#0B1118",
            gradientStop=50,
            gradientDirection="gradientDirectionHorizontal",
            gradientShadingStyle="gradientHorizontalFromRight",
        ),
    )
    return root


def add_frame(root: ET.Element, active: str) -> None:
    add_rect(root, "Header", 0, 0, 1920, 88, "#12202D", "#2E536E", 2)
    add_text(root, "Title", "SL15 装船机仿真监视", 38, 14, 820, 48, color="#FFFFFF", size=30, bold=True)
    add_text(
        root,
        "ReadOnlyBanner",
        "只读监视 · 不向 PLC 写入控制命令",
        1210,
        21,
        660,
        38,
        color="#FFD166",
        size=18,
        bold=True,
        align="middleRight",
    )
    add_rect(root, "Sidebar", 0, 88, 230, 938, "#101922", "#2A3C4E", 1)
    add_button(root, "NavOverview", "运行总览", "Display SL15_Overview", 24, 124, 182, 66, 1, active=active == "overview")
    add_button(root, "NavDiagnostics", "PLC 诊断", "Display SL15_Diagnostics", 24, 208, 182, 66, 2, active=active == "diagnostics")
    add_text(root, "ShortcutLabel", "数据源快捷方式", 24, 332, 182, 28, color="#7F96A8", size=14, bold=False)
    add_text(root, "ShortcutValue", "plc_sl", 24, 366, 182, 40, color="#33C4FF", size=22, bold=True)
    add_text(root, "SafetyNote", "本画面仅用于仿真反馈监视\n现场联锁与安全逻辑以 PLC 为准", 24, 850, 182, 98, color="#8FA4B5", size=14, align="middleCenter")
    add_rect(root, "Footer", 0, 1026, 1920, 54, "#12202D", "#2E536E", 1)
    add_text(root, "FooterText", "SL15 HIL Monitor · FactoryTalk View SE 10.0", 30, 1034, 860, 32, color="#86A0B3", size=14)
    add_text(root, "FooterMode", "MODE: MONITOR ONLY", 1480, 1034, 390, 32, color="#FFD166", size=14, bold=True, align="middleRight")


def axis_card(
    root: ET.Element,
    index: int,
    title: str,
    unit: str,
    x: int,
    y: int,
    accent: str,
) -> None:
    add_rect(root, f"AxisCard{index}", x, y, 304, 218, "#15212C", accent, 2)
    add_rect(root, f"AxisAccent{index}", x, y, 8, 218, accent, accent, 1)
    add_text(root, f"AxisTitle{index}", title, x + 26, y + 20, 250, 36, color="#B7C8D6", size=18, bold=True)
    add_numeric(
        root,
        f"AxisActual{index}",
        tag(f"SL15_HIL_AxisActual[{index}]"),
        x + 24,
        y + 74,
        202,
        62,
        decimals=3,
        field_length=11,
        size=28,
        fill="#0C141C",
    )
    add_text(root, f"AxisUnit{index}", unit, x + 230, y + 88, 54, 38, color=accent, size=18, bold=True, align="middleCenter")
    add_text(root, f"AxisIndex{index}", f"AxisActual[{index}]", x + 24, y + 160, 250, 32, color="#71889A", size=13)


def build_overview() -> ET.Element:
    root = make_root()
    add_frame(root, "overview")

    add_text(root, "StatusSection", "系统状态", 260, 112, 500, 38, color="#FFFFFF", size=24, bold=True)
    add_bool_indicator(
        root,
        "PlcConnected",
        tag("SL15_HIL_AppConnected"),
        260,
        164,
        300,
        74,
        off_caption="PLC 未连接",
        on_caption="PLC 已连接",
    )
    add_bool_indicator(
        root,
        "SimulationRunning",
        tag("SL15_HIL_SimRunning"),
        580,
        164,
        300,
        74,
        off_caption="仿真停止",
        on_caption="仿真运行",
        off_color="#56616B",
        on_color="#177A91",
    )
    add_bool_indicator(
        root,
        "BeltRunning",
        tag("SL15_HIL_BeltRunning"),
        900,
        164,
        300,
        74,
        off_caption="皮带停止",
        on_caption="皮带运行",
        off_color="#56616B",
        on_color="#B57613",
    )
    add_rect(root, "HeartbeatCard", 1220, 164, 650, 74, "#15212C", "#2A3C4E", 2)
    add_text(root, "HeartbeatLabel", "应用心跳", 1242, 180, 150, 38, color="#9EB2C2", size=17, bold=True)
    add_numeric(root, "Heartbeat", tag("SL15_HIL_AppHeartbeat"), 1400, 174, 200, 48, decimals=0, field_length=10, size=22)
    add_text(root, "HeartbeatHint", "应持续递增", 1620, 180, 220, 38, color="#6FC3DF", size=15, align="middleCenter")

    add_text(root, "AxisSection", "五轴实际位置", 260, 272, 500, 38, color="#FFFFFF", size=24, bold=True)
    cards = (
        (0, "大车行走", "m", "#4DA3FF"),
        (1, "臂架回转", "deg", "#57D3A1"),
        (2, "臂架俯仰", "deg", "#FFD166"),
        (3, "臂架伸缩", "m", "#B28DFF"),
        (4, "溜筒回转", "deg", "#FF8C66"),
    )
    for i, title, unit, accent in cards:
        axis_card(root, i, title, unit, 260 + i * 322, 326, accent)

    add_text(root, "RuntimeSection", "运行反馈", 260, 580, 500, 38, color="#FFFFFF", size=24, bold=True)
    add_rect(root, "RuntimePanel", 260, 632, 1040, 340, "#15212C", "#2A3C4E", 2)
    runtime_values = (
        ("SimTimeLabel", "仿真时间", "SimTime", "SL15_HIL_SimTime_ms", "ms", 290, 676, 0),
        ("BeltSpeedLabel", "皮带速度", "BeltSpeed", "SL15_HIL_BeltSpeed_mps", "m/s", 290, 758, 3),
        ("AckSeqLabel", "应答序号", "AckSeq", "SL15_HIL_AckSeq", "", 290, 840, 0),
        ("AckCodeLabel", "应答代码", "AckCode", "SL15_HIL_AckCode", "", 790, 676, 0),
        ("ErrorLabel", "最后错误码", "LastError", "SL15_HIL_LastErrorCode", "", 790, 758, 0),
    )
    for label_name, label, value_name, plc_tag, unit, x, y, decimals in runtime_values:
        add_text(root, label_name, label, x, y, 170, 44, color="#A7BAC9", size=17, bold=True)
        add_numeric(root, value_name, tag(plc_tag), x + 178, y, 210, 44, decimals=decimals, field_length=12, size=20)
        if unit:
            add_text(root, f"{value_name}Unit", unit, x + 398, y, 72, 44, color="#6FC3DF", size=15, align="middleCenter")

    add_rect(root, "MaskPanel", 1320, 632, 550, 340, "#15212C", "#2A3C4E", 2)
    add_text(root, "MaskTitle", "轴状态位掩码", 1350, 654, 470, 36, color="#FFFFFF", size=21, bold=True)
    masks = (
        ("RunningMask", "运行", "SL15_HIL_AxisRunningMask", 708, "#4DA3FF"),
        ("TargetMask", "到位", "SL15_HIL_AxisAtTargetMask", 786, "#57D3A1"),
        ("FaultMask", "故障", "SL15_HIL_AxisFaultMask", 864, "#FF6B78"),
    )
    for name, label, plc_tag, y, color in masks:
        add_text(root, f"{name}Label", label, 1350, y, 100, 46, color=color, size=18, bold=True)
        add_numeric(root, name, tag(plc_tag), 1460, y, 250, 46, decimals=0, field_length=12, size=20)
        add_text(root, f"{name}Hint", "bit0…bit4", 1720, y, 120, 46, color="#71889A", size=13, align="middleCenter")
    return root


def build_diagnostics() -> ET.Element:
    root = make_root()
    add_frame(root, "diagnostics")
    add_text(root, "DiagSection", "PLC / HIL 诊断", 260, 112, 600, 38, color="#FFFFFF", size=24, bold=True)

    add_bool_indicator(
        root,
        "DiagPlcConnected",
        tag("SL15_HIL_AppConnected"),
        260,
        164,
        300,
        74,
        off_caption="PLC 未连接",
        on_caption="PLC 已连接",
    )
    add_bool_indicator(
        root,
        "DiagSimRunning",
        tag("SL15_HIL_SimRunning"),
        580,
        164,
        300,
        74,
        off_caption="仿真停止",
        on_caption="仿真运行",
        off_color="#56616B",
        on_color="#177A91",
    )
    add_bool_indicator(
        root,
        "DiagBeltRunning",
        tag("SL15_HIL_BeltRunning"),
        900,
        164,
        300,
        74,
        off_caption="皮带停止",
        on_caption="皮带运行",
        off_color="#56616B",
        on_color="#B57613",
    )

    add_rect(root, "CommPanel", 260, 280, 770, 670, "#15212C", "#2A3C4E", 2)
    add_text(root, "CommTitle", "通信与任务反馈", 292, 304, 690, 38, color="#FFFFFF", size=22, bold=True)
    comm_rows = (
        ("DiagHeartbeat", "应用心跳", "SL15_HIL_AppHeartbeat", 370),
        ("DiagAckSeq", "应答序号", "SL15_HIL_AckSeq", 438),
        ("DiagAckCode", "应答代码", "SL15_HIL_AckCode", 506),
        ("DiagSimTime", "仿真时间 / ms", "SL15_HIL_SimTime_ms", 574),
        ("DiagRunMask", "轴运行掩码", "SL15_HIL_AxisRunningMask", 642),
        ("DiagTargetMask", "轴到位掩码", "SL15_HIL_AxisAtTargetMask", 710),
        ("DiagFaultMask", "轴故障掩码", "SL15_HIL_AxisFaultMask", 778),
        ("DiagLastError", "最后错误码", "SL15_HIL_LastErrorCode", 846),
    )
    for name, label, plc_tag, y in comm_rows:
        add_text(root, f"{name}Label", label, 300, y, 250, 44, color="#A7BAC9", size=17, bold=True)
        add_numeric(root, name, tag(plc_tag), 570, y, 380, 44, decimals=0, field_length=14, size=20)

    add_rect(root, "FaultPanel", 1054, 280, 816, 670, "#15212C", "#2A3C4E", 2)
    add_text(root, "FaultTitle", "五轴故障代码", 1086, 304, 730, 38, color="#FFFFFF", size=22, bold=True)
    fault_axes = ("大车行走", "臂架回转", "臂架俯仰", "臂架伸缩", "溜筒回转")
    accent_colors = ("#4DA3FF", "#57D3A1", "#FFD166", "#B28DFF", "#FF8C66")
    for i, (axis, color) in enumerate(zip(fault_axes, accent_colors)):
        y = 374 + i * 98
        add_rect(root, f"FaultRow{i}", 1086, y, 750, 74, "#101922", color, 1)
        add_text(root, f"FaultAxis{i}", f"{i}  {axis}", 1110, y + 14, 260, 44, color=color, size=18, bold=True)
        add_numeric(
            root,
            f"AxisFaultCode{i}",
            tag(f"SL15_HIL_AxisFaultCode[{i}]"),
            1390,
            y + 14,
            250,
            44,
            decimals=0,
            field_length=12,
            size=20,
        )
        add_text(root, f"FaultCodeHint{i}", "0 = 无故障", 1650, y + 14, 160, 44, color="#71889A", size=13, align="middleCenter")
    add_text(
        root,
        "DiagNote",
        "诊断说明：心跳应持续递增；连接标志为 1；故障代码为 0 时表示模拟器未上报该轴故障。",
        1086,
        876,
        750,
        50,
        color="#8FA4B5",
        size=14,
        align="middleCenter",
    )
    return root


def write_xml(root: ET.Element, path: Path) -> None:
    ET.indent(root, space="    ")
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    displays = {
        "SL15_Overview.xml": build_overview(),
        "SL15_Diagnostics.xml": build_diagnostics(),
    }
    for filename, root in displays.items():
        write_xml(root, OUTPUT_DIR / filename)

    batch = ET.Element("gfxImport")
    for filename in displays:
        ET.SubElement(batch, "import", attrs(importFile=filename))
    ET.indent(batch, space="    ")
    ET.ElementTree(batch).write(
        OUTPUT_DIR / "BatchImport_SL15.xml",
        encoding="utf-8",
        xml_declaration=True,
        short_empty_elements=True,
    )

    source_schema = ROOT / "work" / "ftview" / SCHEMA_NAME
    if source_schema.exists():
        (OUTPUT_DIR / SCHEMA_NAME).write_bytes(source_schema.read_bytes())

    print(f"Generated {len(displays)} displays in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
