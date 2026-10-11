<template>
  <header class="app-header">
    <div class="header-inner">
      <RouterLink to="/" class="brand" aria-label="Ride Analytics home">
        <span class="brand-mark" aria-hidden="true">↗</span>
        <span>Ride<span class="brand-light">Analytics</span></span>
      </RouterLink>
      <nav aria-label="Main navigation">
        <RouterLink to="/" class="nav-link" exact-active-class="nav-active">Dashboard</RouterLink>
        <RouterLink to="/dashboard-v2" class="nav-link" exact-active-class="nav-active">Event Dashboard</RouterLink>
        <RouterLink to="/settings" class="nav-link" exact-active-class="nav-active">Metrics Settings</RouterLink>
        <RouterLink to="/generator" class="nav-link" exact-active-class="nav-active">Generator</RouterLink>
      </nav>
      <span class="zone-badge">ZONE_1</span>
    </div>
  </header>
  <main class="page"><RouterView /></main>
  <footer class="app-footer">Ride Analytics <span>Operational metrics · Zone 1</span></footer>
</template>
