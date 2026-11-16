# macOS only, behind an Automation interface; click via the accessibility tree

Only a macOS Automation layer exists, because that's the development machine. Commands talk to an abstract interface, so another OS means writing one class. Click-by-label reads the foreground window's accessibility (AX) tree, collects labeled clickable elements, asks Jev to choose one, and presses it through AX, falling back to a synthetic mouse click at the element's center. Chromium and Electron apps are asked to build their web accessibility tree first, and Safari gets the equivalent attribute.

## Considered Options

- **Screenshot plus Jev's Box primitive.** Rejected for now. It needs Screen Recording permission, sends an image per click, and returns a location rather than a semantic element. The AX tree gives exact labels and a press action, at the cost of depending on how well each app exposes accessibility.

## Consequences

The tool needs Accessibility, Input Monitoring, and Microphone permissions for whichever app runs it. Apps with poor accessibility labels can't be clicked by name.
