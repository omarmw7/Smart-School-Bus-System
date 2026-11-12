// Service Worker: يعرض إشعارات الـ Web Push حتى لو الصفحة مسكّرة.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = { title: "مسار", body: "", url: "/" };
  try { data = { ...data, ...event.data.json() }; } catch (_) {}
  event.waitUntil(self.registration.showNotification(data.title || "مسار", {
    body: data.body,
    data: { url: data.url || "/" },
    lang: "ar",
    dir: "rtl",
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(self.clients.openWindow(target));
});
