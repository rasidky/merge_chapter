import os
import re
import shutil
import tempfile
import zipfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from datetime import datetime

# This Program used for merging multiple files into one cbz file and renaming images sequentially across all archives.

# Optional RAR support
try:
    import rarfile
    HAS_RAR = True
except ImportError:
    HAS_RAR = False

IMAGE_EXTENSIONS = {".jpg", ".png", ".webp", ".avif"}
ARCHIVE_EXTENSIONS = {".cbz", ".zip", ".rar"} if HAS_RAR else {".cbz", ".zip"}


def natural_key(path):
    text = str(path.name) if hasattr(path, 'name') else str(path)
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", text)]


def safe_extract(archive_path, extract_dir):
    archive_path = Path(archive_path)
    extract_dir = Path(extract_dir).resolve()
    ext = archive_path.suffix.lower()

    if ext in (".cbz", ".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            bad = []
            for info in zf.infolist():
                target = (extract_dir / info.filename).resolve()
                try:
                    target.relative_to(extract_dir)
                except ValueError:
                    bad.append(info.filename)
            if bad:
                raise RuntimeError("Archive contains unsafe paths:\n" + "\n".join(bad[:10]))
            zf.extractall(extract_dir)
    elif ext == ".rar":
        if not HAS_RAR:
            raise RuntimeError("rarfile module not installed. Install with: pip install rarfile")
        with rarfile.RarFile(archive_path) as rf:
            rf.extractall(extract_dir)
            # Verify no file outside extract_dir
            for root, dirs, files in os.walk(extract_dir):
                for f in files:
                    full = Path(root) / f
                    try:
                        full.relative_to(extract_dir)
                    except ValueError:
                        raise RuntimeError(f"Archive contains unsafe path: {full}")
    else:
        raise ValueError(f"Unsupported archive format: {ext}")


def collect_images(root):
    root = Path(root)
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    return sorted(files, key=natural_key)


def unique_path(path):
    path = Path(path)
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def repack_cbz(source_root, output_cbz):
    source_root = Path(source_root)
    output_cbz = Path(output_cbz)
    output_cbz.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_cbz, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        all_files = sorted(
            [p for p in source_root.rglob("*") if p.is_file()],
            key=lambda p: natural_key(p.relative_to(source_root))
        )
        for file_path in all_files:
            arcname = file_path.relative_to(source_root).as_posix()
            zf.write(file_path, arcname)


def get_archives_recursive(input_folder):
    """Return list of (archive_path, parent_folder_name) for all archives in subfolders."""
    input_path = Path(input_folder)
    archives = []
    for p in input_path.rglob("*"):
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTENSIONS:
            parent_name = p.parent.name
            archives.append((p, parent_name))
    # Sort by parent folder name naturally to keep chapters in order
    archives.sort(key=lambda x: natural_key(x[0].parent))
    return archives


class ComicApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Comic CBZ Sequential Renamer + Merge All (Recursive)")
        self.root.geometry("1050x720")
        self.root.minsize(880, 600)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.start_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Ready.")
        self.archive_data = {}  # map tree item -> (archive_path, parent_folder_name)

        self.build_ui()

    def build_ui(self):
        main = ttk.Frame(self.root, padding=15)
        main.pack(fill="both", expand=True)

        title = ttk.Label(main, text="Comic CBZ Sequential Renamer + Merge All",
                          font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w", pady=(0, 12))

        desc = ttk.Label(main,
            text="Recursively scans for archives in subfolders.\n"
                 "Select one or more archives, then click 'Process Selected' to merge them into one CBZ.\n"
                 "Images are renumbered sequentially across selected archives; other files are preserved in subfolders named after the parent folder.",
            wraplength=960)
        desc.pack(anchor="w", pady=(0, 15))

        # Input folder
        input_frame = ttk.LabelFrame(main, text="Input Folder", padding=10)
        input_frame.pack(fill="x", pady=5)
        ttk.Entry(input_frame, textvariable=self.input_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(input_frame, text="Browse...", command=self.choose_input).pack(side="right")

        # Output folder
        output_frame = ttk.LabelFrame(main, text="Output Folder", padding=10)
        output_frame.pack(fill="x", pady=5)
        ttk.Entry(output_frame, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(output_frame, text="Browse...", command=self.choose_output).pack(side="right")

        # Start number
        number_frame = ttk.Frame(main)
        number_frame.pack(fill="x", pady=8)
        ttk.Label(number_frame, text="Starting number:").pack(side="left")
        ttk.Entry(number_frame, textvariable=self.start_var, width=10).pack(side="left", padx=8)
        ttk.Label(number_frame, text="Example: 1 → 001, 002...   |   51 → 051, 052...").pack(side="left")

        # Buttons
        button_frame = ttk.Frame(main)
        button_frame.pack(fill="x", pady=8)

        ttk.Button(button_frame, text="Scan Folder", command=self.scan_folder).pack(side="left", padx=(0, 8))
        self.process_all_button = ttk.Button(button_frame, text="Process All",
                                             command=lambda: self.process_merge(selected_only=False))
        self.process_all_button.pack(side="left", padx=(0, 8))
        self.process_selected_button = ttk.Button(button_frame, text="Process Selected",
                                                  command=lambda: self.process_merge(selected_only=True))
        self.process_selected_button.pack(side="left")

        # Table
        table_frame = ttk.LabelFrame(main, text="Detected Archives", padding=8)
        table_frame.pack(fill="both", expand=True, pady=8)

        columns = ("folder", "archive", "images", "range")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("folder", text="Parent Folder")
        self.tree.heading("archive", text="Archive File")
        self.tree.heading("images", text="Image Count")
        self.tree.heading("range", text="Number Range")
        self.tree.column("folder", width=250)
        self.tree.column("archive", width=250)
        self.tree.column("images", width=120, anchor="center")
        self.tree.column("range", width=180, anchor="center")

        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Progress
        self.progress = ttk.Progressbar(main, mode="determinate")
        self.progress.pack(fill="x", pady=(5, 3))
        ttk.Label(main, textvariable=self.status_var).pack(anchor="w")

    def choose_input(self):
        folder = filedialog.askdirectory(title="Select input folder")
        if folder:
            self.input_var.set(folder)
            self.scan_folder()

    def choose_output(self):
        folder = filedialog.askdirectory(title="Select output folder")
        if folder:
            self.output_var.set(folder)

    def scan_folder(self):
        input_folder = self.input_var.get().strip()
        if not input_folder:
            messagebox.showwarning("Input Required", "Please select an input folder.")
            return
        input_path = Path(input_folder)
        if not input_path.is_dir():
            messagebox.showerror("Invalid Folder", "Input folder does not exist.")
            return

        archives = get_archives_recursive(input_path)
        self.archive_data.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

        if not archives:
            self.status_var.set("No .cbz, .zip or .rar files found in any subfolder.")
            messagebox.showinfo("No Archives", "No supported archives were found.")
            return

        current = int(self.start_var.get() or "1")
        with tempfile.TemporaryDirectory(prefix="comic_scan_") as temp:
            for archive_path, parent_name in archives:
                work_dir = Path(temp) / parent_name
                work_dir.mkdir(parents=True, exist_ok=True)
                try:
                    safe_extract(archive_path, work_dir)
                    images = collect_images(work_dir)
                    count = len(images)
                    if count:
                        first = current
                        last = current + count - 1
                        range_text = f"{first:03d} - {last:03d}"
                        current = last + 1
                    else:
                        range_text = "-"
                    item = self.tree.insert("", "end", values=(parent_name, archive_path.name, count, range_text))
                    self.archive_data[item] = (archive_path, parent_name)
                except Exception as exc:
                    item = self.tree.insert("", "end", values=(parent_name, archive_path.name, "ERROR", str(exc)))
                    self.archive_data[item] = (archive_path, parent_name)

        self.status_var.set(f"Found {len(archives)} archive(s). Next number: {current}")

    def process_merge(self, selected_only=False):
        """Merge either all or selected archives into one CBZ."""
        input_folder = self.input_var.get().strip()
        output_folder = self.output_var.get().strip()

        if not input_folder or not output_folder:
            messagebox.showwarning("Missing Folders", "Please select both input and output folders.")
            return

        input_path = Path(input_folder)
        output_path = Path(output_folder)
        if not input_path.is_dir():
            messagebox.showerror("Invalid Input", "Input folder does not exist.")
            return

        try:
            start_number = int(self.start_var.get())
            if start_number < 1:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid Number", "Starting number must be a positive integer.")
            return

        # Get items to process
        if selected_only:
            selected_items = self.tree.selection()
            if not selected_items:
                messagebox.showinfo("No Selection", "Please select at least one archive.")
                return
            items = selected_items
        else:
            items = self.tree.get_children()
            if not items:
                messagebox.showinfo("Nothing to Process", "No archives found. Please scan first.")
                return

        # Build list of (archive_path, parent_name) from selected items
        archives_to_process = []
        for item in items:
            data = self.archive_data.get(item)
            if data:
                archives_to_process.append(data)

        if not archives_to_process:
            messagebox.showerror("Error", "No valid archive data found.")
            return

        # Sort by parent folder name naturally
        archives_to_process.sort(key=lambda x: natural_key(x[1]))

        # Confirm
        total = len(archives_to_process)
        if total == 1:
            reply = messagebox.askyesno("Only One Archive",
                                        "Only one archive selected. It will be repacked as a single CBZ.\n"
                                        "Do you want to continue?")
            if not reply:
                return
        else:
            if not messagebox.askyesno("Confirm Merge",
                                       f"Merge {total} archive(s) into ONE .cbz?\n\n"
                                       f"Starting number: {start_number}\n"
                                       f"Output folder: {output_path}"):
                return

        # Disable buttons during operation
        self.process_all_button.config(state="disabled")
        self.process_selected_button.config(state="disabled")
        self.progress["value"] = 0
        self.progress["maximum"] = total

        try:
            with tempfile.TemporaryDirectory(prefix="comic_merge_") as temp:
                temp_root = Path(temp)

                # 1. Extract all archives to separate subfolders named after parent folder
                archive_dirs = []  # list of (parent_name, extract_dir)
                for idx, (archive_path, parent_name) in enumerate(archives_to_process, 1):
                    self.status_var.set(f"Extracting {idx}/{total}: {archive_path.name} (folder: {parent_name})")
                    self.root.update_idletasks()
                    work_dir = temp_root / parent_name
                    work_dir.mkdir(parents=True, exist_ok=True)
                    safe_extract(archive_path, work_dir)
                    archive_dirs.append((parent_name, work_dir))
                    self.progress["value"] = idx
                    self.root.update_idletasks()

                # 2. Collect all images from all archives (in order of archive_dirs)
                all_images = []
                for parent_name, work_dir in archive_dirs:
                    images = collect_images(work_dir)
                    all_images.extend((parent_name, work_dir, img) for img in images)

                # 3. Prepare merged root directory
                merged_root = temp_root / "merged_contents"
                merged_root.mkdir(parents=True, exist_ok=True)

                # 4. Rename and copy images sequentially
                current = start_number
                renamed_count = 0
                for parent_name, work_dir, img_path in all_images:
                    width = max(3, len(str(current)))
                    new_name = f"{current:0{width}d}{img_path.suffix.lower()}"
                    dest = merged_root / new_name
                    if dest.exists():
                        dest = unique_path(dest)
                    shutil.copy2(img_path, dest)
                    current += 1
                    renamed_count += 1

                # 5. Copy all non‑image files into subfolders named after the parent folder
                for parent_name, work_dir in archive_dirs:
                    for root_dir, dirs, files in os.walk(work_dir):
                        root_path = Path(root_dir)
                        for f in files:
                            file_path = root_path / f
                            if file_path.suffix.lower() in IMAGE_EXTENSIONS:
                                continue
                            rel = file_path.relative_to(work_dir)
                            dest = merged_root / parent_name / rel
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(file_path, dest)

                # 6. Repack into final CBZ with timestamp
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_name = f"merged_{timestamp}.cbz"
                output_cbz = output_path / output_name
                if output_cbz.exists():
                    output_cbz = unique_path(output_cbz)

                self.status_var.set("Repacking merged archive...")
                self.root.update_idletasks()
                repack_cbz(merged_root, output_cbz)

                self.status_var.set(f"Merge complete. {renamed_count} images, output: {output_cbz.name}")
                messagebox.showinfo("Merge Completed",
                                    f"Successfully merged {total} archive(s) into one CBZ.\n\n"
                                    f"Images renamed: {renamed_count}\n"
                                    f"Output file: {output_cbz}")

        except Exception as exc:
            messagebox.showerror("Merge Error", f"An error occurred:\n\n{exc}")
            self.status_var.set("Merge failed.")
        finally:
            self.process_all_button.config(state="normal")
            self.process_selected_button.config(state="normal")
            self.progress["value"] = 0


def main():
    root = tk.Tk()
    app = ComicApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()