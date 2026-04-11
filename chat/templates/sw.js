const CACHE_NAME = 'aira-v1';
const STATIC_ASSETS = [
  '/',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png',
];

self.addEventListener('install', function(e){
  e.waitUntil(
    caches.open(CACHE_NAME).then(function(cache){
      return cache.addAll(STATIC_ASSETS);
    })
  );
});

self.addEventListener('fetch', function(e){
  // Only cache GET requests
  if(e.request.method !== 'GET') return;
  // Don't cache API/websocket calls
  if(e.request.url.includes('/send/') || 
     e.request.url.includes('/ws/') ||
     e.request.url.includes('/api/')) return;

  e.respondWith(
    fetch(e.request).catch(function(){
      return caches.match(e.request);
    })
  );
});