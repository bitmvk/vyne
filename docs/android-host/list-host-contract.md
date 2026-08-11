# Portable list host contract

Vyne's list engines are Python policy. Android is one implementation of a
small platform-host contract; it is not the definition of list behavior.

## Python authority

Python owns:

- `VirtualData`, stable keys, and source identity;
- fixed and arbitrary `VirtualLayout` planning;
- bounded realization and measurement caches;
- anchor correction and controller transaction state;
- semantic content width/height;
- sticky edge and section-boundary constraints;
- whether the interactive scrollbar capability is enabled.

The strict reference functions are private in
`vyne._lists.host_contract`. Cross-language cases live in
`tests/fixtures/list_host_contract.json`.

## Host tools

A platform host must provide:

1. canonical view factories in its own registry;
2. actual viewport/content metrics in logical units;
3. its best clamped projected landing offset;
4. native scrolling and accepted scroll targets;
5. cell measurement and compatible view reuse;
6. per-frame sticky displacement from Python's constraints;
7. an optional interactive scrollbar for a canonical scroll container;
8. semantic positioned-content extent enforcement.

These tools must not read item values, keys, layout strategies, or realization
policy. Plain scroll content moves directly. Virtual lists install the internal
`scroll_seek` observation: the native thumb keeps a provisional target while
Python prepares the destination and returns cells plus the ordinary accepted
`scroll_to` effect in one existing transaction. Pointer crossings are limited
to one non-final latest event per 32 ms; release bypasses the throttle. There is
no commit protocol, revision, scheduler, or controller API change.

## Android adapter

Android maps canonical kinds only in `NativeWidgets.kt`.

- `RoundedScrollView` and `RoundedHorizontalScrollView` provide native scroll
  physics, projection, sticky updates, and interactive scrollbar touch.
- `RoundedFrameLayout` enforces `_virtual_content_width` and
  `_virtual_content_height` during measurement. This keeps Android's
  UNSPECIFIED `ScrollView` measurement workaround out of the Python tree.
  Android stores a measured size in 24 bits (`View.MEASURED_SIZE_MASK`). The
  adapter rejects a semantic extent above that device-pixel limit with a clear
  transaction error instead of truncating the scroll range. The limit depends
  on display density; Python does not impose a cross-platform logical maximum.
  Supporting larger Android extents requires future segmented/rebased native
  scrolling. Fixed linear content is also ultimately subject to Android's
  measured-dimension limit even though it uses real spacers rather than these
  positioned-content props; the explicit preflight check currently applies to
  semantic positioned content.
- `VirtualSticky.kt` and `InteractiveScrollbar.kt` are generic host mechanics.
  They contain no list source, key, index, or layout logic.

The interactive indicator is visible only while enabled and scrollable. It is
on the right for vertical content and the bottom for horizontal content. The
visual thumb is 7 logical units thick; the edge hit target is 32; the minimum
main-axis thumb is 40. A track tap centers the thumb at the pointer. A thumb
drag preserves its initial grab offset and remains owned by the pointer that
started it; additional fingers cannot steal or jump the thumb.

For a virtual list, actual native content does not move before acceptance. The
host draws the provisional thumb, emits latest/backpressured targets, and uses
an accepted non-animated `scroll_to` while a target is provisional as implicit
reveal success. No unbounded emitted-target history is retained. A reveal for
an older target is safe but leaves the newest provisional target intact; a
match within one host pixel clears the target to tolerate logical-unit
rounding. Scroll and following layout echoes at the reveal target are
suppressed through one short deadline, while any differing real movement
clears suppression immediately. Final seeks retry after 750 ms at most twice,
then restore the thumb to the actual offset. New gestures, cancellation,
accepted listener removal/disable, detach, view reuse, and a lost active
pointer clear provisional state; candidate listener/property changes preserve
it until acceptance so rollback is lossless. The crossing cost remains; this
handshake prevents an unrealized destination from being exposed while avoiding
a crossing for every pointer frame.

## Future iOS adapter

The iOS host should map canonical kinds to UIKit independently and consume the
same JSON fixture. Expected mappings include a `UIScrollView` content-size
implementation, UIKit's proposed deceleration target as `projected_offset`,
native per-frame sticky/scrollbar mechanics, and the same throttled provisional
`scroll_seek`/accepted-reveal handshake.

Native deceleration curves are intentionally not compared between Android and
iOS. Only clamping and semantic invariants are shared. Horizontal RTL logical
`start`/`end` behavior remains deferred and must be designed once for both
hosts before either adapter claims support.
