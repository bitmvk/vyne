# React Native Core Parity Roadmap

This document defines what Vyne must add to reach parity with **React Native
core**. It also defines what Vyne must **not** add, because those features
belong to the ecosystem layer.

## The principle

React Native core is:

- UI primitives
- basic system integrations
- networking
- animation

Everything else in the RN world — navigation, storage, permissions, push
notifications, camera, OTA updates — is ecosystem. End users pick those from
the community.

Vyne copies the same split:

- **Framework core** = the RN-core equivalent. The framework owns it.
- **Extensions / app code** = the RN ecosystem equivalent. The end user
  builds it, using `extensions/`, `callback()`, and `activity()`.

The baseline for comparison is the official RN core list:
[reactnative.dev/docs/components-and-apis](https://reactnative.dev/docs/components-and-apis).

Note: RN itself moved several features out of core. AsyncStorage, Clipboard,
and Geolocation are now community packages. Those are ecosystem in RN too,
so they are ecosystem in Vyne.

## Already RN-core-equivalent (no work)

| RN core | Vyne has |
|---|---|
| View / SafeAreaView | Box, Column, Row, Layout + `safe_area` + system insets |
| Text, TextInput | Text, TextField (M3) |
| ScrollView | Scroll |
| Button, Pressable, Switch, ActivityIndicator, dialogs | full M3 catalog: buttons, chips, switches, sliders, pickers, Dialog, BottomSheet, Snackbar, Tooltip, progress, tabs, drawers |
| StyleSheet | Style, Decoration |
| Animated, Easing | Animated.Value, timing, spring, parallel, sequence, interpolation |
| FlatList / VirtualizedList core | `List` — windowed rendering, view recycling, keyed reconciliation, native fling projection, scroll-to-index/offset |
| NativeModules / bridge | extensions + `callback()` + `activity()` escape hatch |
| Accessibility | semantics + host tests |
| component state and lifecycle | `state()`, `component()`, async callbacks |
| AppState | `AppState` via `AppContext` — foreground/background, `on_change` handlers |
| BackHandler | `BackHandler` via `AppContext` — system back-press interception |

## Missing for RN-core parity (to add)

| # | RN core feature | What Vyne needs | Effort |
|---|---|---|---|
| 1 | FlatList extras + SectionList | `List` core is done (windowing, recycling, projection, scroll-to-index). Remaining: header/footer/separator, multi-column, sections + sticky headers (`retained_mask` exists for pinned regions) | Medium (List surface) |
| 2 | Network images (`Image source={{uri}}`) | data URIs (`data:image/...;base64,`) already decode off the UI thread with an in-memory cache by source (`ImageDecoder.kt`). Missing: direct URL loading, disk cache, loading/error states | Medium (native pipeline) |
| 3 | fetch / WebSocket (core networking) | async HTTP client + WebSocket bridged into the ordered event runtime. `urllib` exists but is not runtime-integrated | Medium (runtime work) |
| 4 | PanResponder | public gesture API (drag/swipe/pinch) on top of the existing `PointerSession` input routing | Medium |
| 5 | KeyboardAvoidingView + Keyboard API | keyboard inset events (the `safe_area` inset machinery already exists), show/hide/dismiss API | Low-Medium |
| 6 | StatusBar | style, color, visibility control | Low |
| 7 | Modal (core overlay container) | a generic overlay layer; M3 Dialog/BottomSheet cover most cases | Low-Medium |
| 8 | RefreshControl (pull-to-refresh) | sits on Scroll and FlatList | Low |
| 9 | Dimensions + PixelRatio + Platform | screen metrics, density, OS introspection | Trivial (Python + tiny bridge) |
| 10 | Share, Toast, Vibration, Alert, Linking.openURL | small native bridge methods; inbound deep links already exist via `LaunchData` | Trivial-Low |
| 11 | AccessibilityInfo | query/observe screen-reader state (semantics exist; the API surface does not) | Low |
| 12 | Dev surface — Fast Refresh, LogBox, DevSettings | hot reload of app modules preserving state (`bootstrap.py` already has `reload()`), dev error screen | Medium (dev-mode only) |

## Out of framework scope (end user builds)

These are not RN core, so they do not belong in Vyne core. The end user
builds them in Python, or as extensions, or as app code:

| Feature | RN ecosystem counterpart | Why it is out of scope |
|---|---|---|
| Navigation | React Navigation (separate package) | an end user can build stack/tab navigation in Python with `LaunchData`, state, and rendering. BackHandler + AppState already ship, so user-built navigation is unblocked |
| Storage | AsyncStorage (community) | an end user writes a KV module over app-private files |
| Permissions, push notifications, camera, geolocation, sensors, biometrics, clipboard, netinfo, image picker | community modules | all extension-shaped in Vyne |
| OTA updates | CodePush / Expo Updates (ecosystem) | already proven possible app-side; see the OTA design discussion |
| Reanimated, gesture-handler, i18n, device info | ecosystem | same pattern |

## Takeaways

- The framework's UI kit is already RN-complete or better.
- The virtualized-list gap is closed: `List` (windowing, recycling, projection,
  scroll-to-index) shipped. SectionList-style extras remain as one item.
- AppState and BackHandler shipped, so user-built navigation is unblocked.
- The parity gap is 12 items, mostly small.
- Two are real engineering projects:
  1. network images (item 2)
  2. runtime-integrated networking (item 3)
- Everything else is a thin bridge over machinery that already exists.
