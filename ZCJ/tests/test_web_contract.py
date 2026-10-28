from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "web" / "app.js").read_text(encoding="utf-8")
RIG_JS = (
    ROOT / "app" / "web" / "shiploader" / "procedural-rig.js"
).read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "app" / "web" / "index.html").read_text(encoding="utf-8")


def test_web_uses_one_persistent_shiploader_rig():
    assert "new ProceduralShiploaderRig" in APP_JS
    assert "shiploaderRig.update(snapshot)" in APP_JS
    assert "rebuildLoader(" not in APP_JS
    assert "trajectoryCapacity" in APP_JS
    assert "trajectoryGeometry.setDrawRange" in APP_JS


def test_rig_exposes_required_motion_nodes_and_markers():
    for name in (
        "SL_ShipLoaderRoot",
        "SL_TravelAssembly",
        "SL_UpperSlewAssembly",
        "SL_BoomLuffPivot",
        "SL_FixedBoomAssembly",
        "SL_TelescopicBoomAssembly",
        "SL_ChuteAssembly",
        "SL_ChuteYawAssembly",
        "MK_SLEW_CENTER",
        "MK_BOOM_ROOT",
        "MK_FIXED_BOOM_TIP",
        "MK_BOOM_TIP",
        "MK_CHUTE_TOP",
        "MK_CHUTE_BOTTOM",
        "MK_DISCHARGE",
    ):
        assert name in RIG_JS


def test_rig_exposes_sl15_chute_detail_contract():
    for name in (
        "VIS_ChuteSuspensionYoke",
        "VIS_ChuteTopServicePlatform",
        "VIS_ChuteTopRotaryHousing",
        "VIS_ChuteTopMachineryCage",
        "VIS_ChuteTelescopicTrunk",
        "VIS_ChuteGuideFrame",
        "VIS_ChuteInspectionLadder",
        "VIS_ChuteLowerServicePlatform",
        "VIS_ChuteLowerRotaryHead",
        "VIS_ChuteLowerMachineryCage",
        "VIS_ChuteDistributionYoke",
        "VIS_ChuteSingleDischarge",
        "VIS_ChuteHangingCable",
    ):
        assert name in RIG_JS

    assert "VIS_ChuteTwinBranchLeft" not in RIG_JS
    assert "VIS_ChuteTwinBranchRight" not in RIG_JS
    assert "this.chuteAssembly.rotation.y" in RIG_JS
    assert "this.chuteYawAssembly.rotation.y" in RIG_JS
    assert "axes.slew.current + axes.chute_rotate.current" not in RIG_JS


def test_land_side_transfer_is_left_of_portal_in_top_view():
    assert 'feed.name = "VIS_LandSideTransfer"' in RIG_JS
    assert "feed.position.set(-18, visual.portal_height_m + 0.35, 0)" in RIG_JS
    assert "feed.rotation.y = Math.PI / 2" in RIG_JS


def test_all_fixed_view_controls_are_present():
    for view in ("perspective", "front", "side", "top"):
        assert f'data-view="{view}"' in INDEX_HTML


def test_axis_controls_show_and_enforce_target_and_velocity_limits():
    assert "目标为机械行程上下限" in APP_JS
    assert "目标范围" in APP_JS
    assert "速度范围 0 ～" in APP_JS
    assert "aria-describedby" in APP_JS
    assert "targetInput.checkValidity()" in APP_JS
    assert "velocityInput.checkValidity()" in APP_JS


def test_path_planning_panel_and_six_stage_contract_are_present():
    for element_id in (
        "path-vessel-select",
        "path-hold-select",
        "path-column-input",
        "path-row-input",
        "hatch-grid",
        "path-preview-button",
        "path-start-button",
        "path-pause-button",
        "path-resume-button",
        "path-cancel-button",
        "path-stage-list",
    ):
        assert f'id="{element_id}"' in INDEX_HTML

    for stage in (
        "safe_luff",
        "safe_retract",
        "safe_slew",
        "travel",
        "target_luff",
        "final_approach",
    ):
        assert stage in APP_JS

    assert "PATH_SelectedGridCell" in APP_JS
    assert "PATH_TargetPoint" in APP_JS
    assert "PATH_ActualDischarge" in APP_JS
    assert "worldYawToThreeRadians" in APP_JS
    assert 'role="grid"' in INDEX_HTML
    assert "handleGridKeydown" in APP_JS


def test_cover_controls_expose_explicit_open_closed_state():
    assert "data-cover-state" in APP_JS
    assert '<option value="open">已打开</option>' in APP_JS
    assert '<option value="closed">已关闭</option>' in APP_JS


def test_visual_baseline_matrix_is_complete():
    baseline_dir = ROOT / "tests" / "visual-baselines" / "sl15"
    expected_scenes = (
        "s1-initial",
        "s2-low-max-extension",
        "s3-high-min-extension",
        "s4-slew-min",
        "s5-slew-max",
        "s6-chute-90",
    )
    expected_views = ("perspective", "front", "side", "top")
    expected = {
        f"{scene}-{view}.png"
        for scene in expected_scenes
        for view in expected_views
    }
    actual = {path.name for path in baseline_dir.glob("*.png")}
    assert actual == expected | {"chute-detail-front.png"}
