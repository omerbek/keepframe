# Packaging (v0.4)

Plan (see ARCHITECTURE.md §8):

1. `pyinstaller packaging/keepframe.spec` → `dist/KeepFrame/` (onedir, with onnxruntime-directml and the models)
2. `iscc packaging/installer.iss` → `KeepFrame-Setup-x.y.z.exe`
3. Sign with SignPath Foundation (free for open-source projects)
4. Upload to GitHub Release and open a winget PR (`packaging/winget/`)

NVIDIA CUDA add-on: on first launch the user is offered "Download GPU acceleration",
which installs `onnxruntime-gpu[cuda,cudnn]`.
