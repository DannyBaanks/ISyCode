"""The cross-mixin Protocols stay satisfied by the real TUIApp surface (F-05a)."""
from isycode.tui import TUIApp
from isycode.tui_protocols import PROTOCOLS, protocol_members


def test_every_protocol_member_exists_on_the_app():
    for protocol in PROTOCOLS:
        for name in protocol_members(protocol):
            attribute = getattr(TUIApp, name, None)
            assert isinstance(attribute, property) or callable(attribute), \
                f"{protocol.__name__}.{name}"


def test_protocol_members_are_the_real_cross_mixin_surface():
    # The contracts mirror today's measured call graph; a name that no other
    # mixin reaches anymore should leave the Protocol (and vice versa).
    from isycode.tui_protocols import (
        AuthorityController,
        ChatController,
        GusController,
        MenuController,
        ProviderController,
        RailController,
        RemoteController,
        SessionProvider,
        ToolController,
        WorkspaceController,
    )
    assert "_run_chat" in protocol_members(ChatController)
    assert "_lane_on_screen" in protocol_members(SessionProvider)
    assert "_workspace_read_owner" in protocol_members(WorkspaceController)
    assert "_open_palette" in protocol_members(MenuController)
    assert "_apply_rail_width" in protocol_members(RailController)
    assert "_open_gus" in protocol_members(GusController)
    assert "_workspace_mode" in protocol_members(AuthorityController)
    assert "_dispatch_chat_tool" in protocol_members(ToolController)
    assert "_select_provider" in protocol_members(ProviderController)
    assert "_start_mobile_host" in protocol_members(RemoteController)
    assert len(PROTOCOLS) == 10
