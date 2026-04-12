# Phase 8: Strategy IDE

## Goal
Custom strategies can be written in the browser, saved, and hot-loaded into the live engine.

## Tasks Breakdown

### 1. Monaco Editor Integration
- Add the `@monaco-editor/react` package into the frontend application to offer a proper developer experience.
- Inject placeholder strategy templates defining the standard `BaseStrategy` override template inside the IDE editor panel upon creating a "New Strategy".

### 2. Syntax Validation Pipeline
- Upon save execution, transfer the code strings to the Python backend to utilize the native `ast` library, generating syntax checks guaranteeing baseline functionality.
- Evaluate base class compliance (the presence of `scan()`). 

### 3. Hot-Reload Architecture
- Modify the `core/strategy_loader.py` framework to allow immediate runtime injection of compiled strings into memory registries without shutting down the central scanner loop.
- Save valid custom strategies definitively inside a new `strategies` database table.

### 4. User Interface Polish
- Tie together the complete left-panel strategy listing toggle array alongside the central IDE code execution pane. 

## Final Deliverable
Fully operable programmatic scripting directly in the web UI empowering developers to continuously generate or edit strategies rapidly without stopping the backend logic processing.

## Phase 8 Transition Checklist
- [ ] IDE Editor properly handles raw text inputs and indentation
- [ ] Syntax check AST correctly denies Python syntax flaws
- [ ] Base Strategy compliance strictly ensures only functioning strategies proceed
- [ ] Dynamic database reloading correctly instantiates newly committed strats immediately
