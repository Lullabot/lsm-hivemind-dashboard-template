/**
 * Panel reordering with 2-column grid support.
 * Requires Sortable.js to be loaded first.
 *
 * Features:
 * - Drag panels vertically to reorder
 * - Drag a panel onto the right-side drop zone of another panel to create a 2-col row
 * - Drag a panel out of a 2-col row back to full width
 * - All layout persisted to localStorage per page
 */
(function() {
  if (typeof Sortable === 'undefined') return;

  var BASE_KEY = 'pmdashboard-panel-order-' + window.location.pathname;

  function keyFor(container) {
    var sub = container && container.dataset && container.dataset.sortKey;
    return sub ? BASE_KEY + '-' + sub : BASE_KEY;
  }

  var HANDLE_SVG = '<span class="drag-handle" title="Drag to reorder">' +
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">' +
    '<circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/>' +
    '<circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/>' +
    '<circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/>' +
    '</svg></span>';

  function loadOrder(container) {
    try { return JSON.parse(localStorage.getItem(keyFor(container))) || null; }
    catch (e) { return null; }
  }

  /**
   * Save layout: ordered list where each entry is a panel ID string
   * or an array of IDs (2-col grid row).
   */
  function saveLayout(container) {
    var layout = [];
    Array.from(container.children).forEach(function(el) {
      if (el.classList.contains('detail-grid')) {
        var gridIds = [];
        el.querySelectorAll(':scope > [data-panel-id]').forEach(function(child) {
          gridIds.push(child.getAttribute('data-panel-id'));
        });
        if (gridIds.length) layout.push(gridIds);
      } else if (el.hasAttribute('data-panel-id')) {
        layout.push(el.getAttribute('data-panel-id'));
      }
    });
    localStorage.setItem(keyFor(container), JSON.stringify(layout));
  }

  function restoreLayout(container) {
    var layout = loadOrder(container);
    if (!layout || !layout.length) return;

    // Collect all panels
    var panels = {};
    container.querySelectorAll('[data-panel-id]').forEach(function(el) {
      panels[el.getAttribute('data-panel-id')] = el;
    });

    // Remove existing grids
    container.querySelectorAll(':scope > .detail-grid').forEach(function(g) {
      // Move children out before removing
      while (g.firstChild) container.appendChild(g.firstChild);
      g.remove();
    });

    var fragment = document.createDocumentFragment();
    var placed = {};

    layout.forEach(function(entry) {
      if (Array.isArray(entry)) {
        var grid = document.createElement('div');
        grid.className = 'detail-grid';
        entry.forEach(function(id) {
          if (panels[id]) {
            grid.appendChild(panels[id]);
            placed[id] = true;
          }
        });
        if (grid.children.length) fragment.appendChild(grid);
      } else {
        if (panels[entry]) {
          fragment.appendChild(panels[entry]);
          placed[entry] = true;
        }
      }
    });

    // Append unplaced panels
    Object.keys(panels).forEach(function(id) {
      if (!placed[id]) fragment.appendChild(panels[id]);
    });

    // Clear and rebuild
    while (container.firstChild) container.removeChild(container.firstChild);
    container.appendChild(fragment);

    // Clean up any single-child grids (e.g. saved layout with a missing panel)
    cleanEmptyGrids(container);
  }

  // Inject drag handles
  function injectHandles(container) {
    container.querySelectorAll('[data-panel-id]').forEach(function(panel) {
      if (panel.querySelector('.drag-handle')) return;
      var header = panel.querySelector('.section-header') ||
                   panel.querySelector('.collapsible-toggle') ||
                   panel.querySelector('.page-header');
      if (header) {
        header.insertAdjacentHTML('afterbegin', HANDLE_SVG);
      } else {
        panel.style.position = 'relative';
        panel.insertAdjacentHTML('afterbegin',
          '<span class="drag-handle drag-handle-float" title="Drag to reorder">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">' +
          '<circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/>' +
          '<circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/>' +
          '<circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/>' +
          '</svg></span>');
      }
    });
  }

  // Create side drop zones (for 2-col) and full-width drop zones (for breaking out)
  function createDropZones(container) {
    function refreshZones() {
      // Remove old zones
      container.querySelectorAll('.panel-drop-zone, .fullwidth-drop-zone').forEach(function(z) { z.remove(); });

      // Add right-side zones to single-column panels (for creating 2-col)
      Array.from(container.children).forEach(function(el) {
        if (el.hasAttribute('data-panel-id') && !el.closest('.detail-grid')) {
          el.style.position = 'relative';
          var zone = document.createElement('div');
          zone.className = 'panel-drop-zone';
          zone.setAttribute('data-target-panel', el.getAttribute('data-panel-id'));
          el.appendChild(zone);
        }
      });

      // Add full-width drop zones between top-level elements
      // These allow dropping a panel as full-width between existing rows
      var children = Array.from(container.children);
      children.forEach(function(el, i) {
        // Add a zone before each element (so there's always one between items)
        var fwZone = document.createElement('div');
        fwZone.className = 'fullwidth-drop-zone';
        fwZone.setAttribute('data-insert-before', i.toString());
        container.insertBefore(fwZone, el);
      });
      // Add one after the last element too
      var lastZone = document.createElement('div');
      lastZone.className = 'fullwidth-drop-zone';
      lastZone.setAttribute('data-insert-before', 'end');
      container.appendChild(lastZone);
    }

    var draggedPanel = null;

    // Track drag start/end to show/hide zones
    container.addEventListener('mousedown', function(e) {
      var handle = e.target.closest('.drag-handle');
      if (!handle) return;
      draggedPanel = handle.closest('[data-panel-id]');
      // Small delay to let sortable start
      setTimeout(function() {
        if (draggedPanel) {
          container.classList.add('is-dragging');
          refreshZones();
          // Hide side zone on the dragged panel itself
          var selfZone = draggedPanel.querySelector('.panel-drop-zone');
          if (selfZone) selfZone.style.display = 'none';
          // Hide full-width zones adjacent to the dragged panel (no-op drop)
          var isInGrid = draggedPanel.closest('.detail-grid');
          if (!isInGrid) {
            // Find full-width zones immediately before/after this panel
            var prev = draggedPanel.previousElementSibling;
            var next = draggedPanel.nextElementSibling;
            if (prev && prev.classList.contains('fullwidth-drop-zone')) prev.style.display = 'none';
            if (next && next.classList.contains('fullwidth-drop-zone')) next.style.display = 'none';
          }
        }
      }, 100);
    });

    document.addEventListener('mouseup', function() {
      draggedPanel = null;
      container.classList.remove('is-dragging');
      container.querySelectorAll('.panel-drop-zone, .fullwidth-drop-zone').forEach(function(z) { z.remove(); });
    });

    // Handle drops on zones
    container.addEventListener('mouseup', function(e) {
      var sideZone = e.target.closest('.panel-drop-zone');
      var fwZone = e.target.closest('.fullwidth-drop-zone');

      if (!draggedPanel) return;

      if (sideZone) {
        // Side zone: create 2-col layout
        var targetId = sideZone.getAttribute('data-target-panel');
        var targetPanel = container.querySelector('[data-panel-id="' + targetId + '"]');
        if (!targetPanel || targetPanel === draggedPanel) return;

        var parentGrid = targetPanel.closest('.detail-grid');
        if (parentGrid && parentGrid.children.length < 2) {
          parentGrid.appendChild(draggedPanel);
        } else if (!parentGrid) {
          var grid = document.createElement('div');
          grid.className = 'detail-grid';
          targetPanel.parentNode.insertBefore(grid, targetPanel);
          grid.appendChild(targetPanel);
          grid.appendChild(draggedPanel);
          initGridSortable(grid, container);
        }
      } else if (fwZone) {
        // Full-width zone: place panel as full-width at this position
        // Remove panel from its current grid if inside one
        container.insertBefore(draggedPanel, fwZone);
      } else {
        return;
      }

      // Clean up empty grids and stale zones
      container.querySelectorAll('.fullwidth-drop-zone').forEach(function(z) { z.remove(); });
      cleanEmptyGrids(container);
      saveLayout(container);
      injectHandles(container);
      draggedPanel = null;
      container.classList.remove('is-dragging');
      container.querySelectorAll('.panel-drop-zone').forEach(function(z) { z.remove(); });
    });

    return refreshZones;
  }

  function cleanEmptyGrids(container) {
    container.querySelectorAll(':scope > .detail-grid').forEach(function(grid) {
      if (grid.children.length === 0) {
        grid.remove();
      } else if (grid.children.length === 1) {
        // Unwrap single child back to main flow
        var child = grid.children[0];
        grid.parentNode.insertBefore(child, grid);
        grid.remove();
      }
    });
  }

  function initGridSortable(grid, container) {
    Sortable.create(grid, {
      animation: 150,
      handle: '.drag-handle',
      ghostClass: 'panel-ghost',
      chosenClass: 'panel-chosen',
      dragClass: 'panel-drag',
      group: 'panels',
      onEnd: function() {
        cleanEmptyGrids(container);
        saveLayout(container);
      }
    });
  }

  document.querySelectorAll('.sortable-panels').forEach(function(container) {
    restoreLayout(container);
    injectHandles(container);
    createDropZones(container);

    // Main container sortable
    Sortable.create(container, {
      animation: 150,
      handle: '.drag-handle',
      ghostClass: 'panel-ghost',
      chosenClass: 'panel-chosen',
      dragClass: 'panel-drag',
      group: 'panels',
      onEnd: function() {
        cleanEmptyGrids(container);
        saveLayout(container);
      }
    });

    // Init sortable on existing grids
    container.querySelectorAll(':scope > .detail-grid').forEach(function(grid) {
      initGridSortable(grid, container);
    });
  });
})();
