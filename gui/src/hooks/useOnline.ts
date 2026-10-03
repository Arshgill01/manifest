import { useSyncExternalStore } from "react";

const subscribe = (cb: () => void) => {
  window.addEventListener("online", cb);
  window.addEventListener("offline", cb);
  return () => {
    window.removeEventListener("online", cb);
    window.removeEventListener("offline", cb);
  };
};

/** The machine's network state. Flips the moment Wi-Fi goes off; the GUI itself never touches the network. */
export function useNetworkOnline() {
  return useSyncExternalStore(subscribe, () => navigator.onLine, () => true);
}
