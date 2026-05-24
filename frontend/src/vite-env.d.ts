/// <reference types="vite/client" />

interface Window {
    showDirectoryPicker(options?: {
        mode?: "read" | "readwrite";
        startIn?:
            | "desktop"
            | "documents"
            | "downloads"
            | "music"
            | "pictures"
            | "videos";
    }): Promise<FileSystemDirectoryHandle>;
}

interface FileSystemDirectoryHandle {
    readonly name: string;
}
