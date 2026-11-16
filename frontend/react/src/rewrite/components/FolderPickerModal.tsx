import { FolderPickerDialog } from "../features/folderPicker/FolderPickerDialog";
import { useAppStore } from "../state/appStore";

/**
 * 文件夹选择器挂载点。
 * 关闭时直接卸载，因此每次打开都会重新读取 system/env 并回到初始路径。
 */
export function FolderPickerModal() {
  const open = useAppStore((state) => state.folderPickerOpen);

  return open ? <FolderPickerDialog /> : null;
}
