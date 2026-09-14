(() => {
  const symbolSelect = document.getElementById("symbol");
  const traderIdInput = document.getElementById("trader-id");
  const connStatus = document.getElementById("conn-status");
  const bboBid = document.getElementById("bbo-bid");
  const bboAsk = document.getElementById("bbo-ask");
  const bboSpread = document.getElementById("bbo-spread");
  const bidsBody = document.getElementById("bids-body");
  const asksBody = document.getElementById("asks-body");
  const tradeTape = document.getElementById("trade-tape");
  const openOrdersEl = document.getElementById("open-orders");
  const orderForm = document.getElementById("order-form");
  const feedback = document.getElementById("order-feedback");
  const submitBtn = document.getElementById("submit-btn");
  const priceField = document.getElementById("price-field");
  const priceInput = document.getElementById("price");
  const stopPriceField = document.getElementById("stop-price-field");
  const stopPriceInput = document.getElementById("stop_price");
  const quantityInput = document.getElementById("quantity");
  const orderTypeSelect = document.getElementById("order_type");
  const sideButtons = document.querySelectorAll(".side-btn");

  const PRICE_REQUIRED_TYPES = new Set(["limit", "ioc", "fok", "stop_limit"]);
  const STOP_PRICE_REQUIRED_TYPES = new Set(["stop", "stop_limit", "take_profit"]);

  let currentSymbol = symbolSelect.value;
  let currentSide = "buy";
  let ws = null;
  let reconnectTimer = null;
  let openOrdersPoll = null;
  const seenTradeIds = new Set();

  // ---------------------------
  // Trader identity (persisted per browser, not a real login)
  // ---------------------------
  traderIdInput.value = localStorage.getItem("matching_engine_trader_id") || "";
  traderIdInput.addEventListener("input", () => {
    localStorage.setItem("matching_engine_trader_id", traderIdInput.value.trim());
    refreshOpenOrders();
  });

  function currentTraderId() {
    return traderIdInput.value.trim();
  }

  // ---------------------------
  // Order form interactions
  // ---------------------------
  sideButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      sideButtons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentSide = btn.dataset.side;
      submitBtn.className = `submit-btn ${currentSide}`;
      submitBtn.textContent = currentSide === "buy" ? "Place Buy Order" : "Place Sell Order";
    });
  });

  function updateFieldVisibility() {
    const orderType = orderTypeSelect.value;
    priceField.style.display = PRICE_REQUIRED_TYPES.has(orderType) ? "flex" : "none";
    stopPriceField.style.display = STOP_PRICE_REQUIRED_TYPES.has(orderType) ? "flex" : "none";
  }
  orderTypeSelect.addEventListener("change", updateFieldVisibility);
  updateFieldVisibility();

  orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    feedback.textContent = "";
    feedback.className = "feedback";

    const traderId = currentTraderId();
    if (!traderId) {
      feedback.textContent = "Enter a trader name first.";
      feedback.className = "feedback err";
      return;
    }

    const orderType = orderTypeSelect.value;
    const payload = {
      symbol: currentSymbol,
      order_type: orderType,
      side: currentSide,
      quantity: quantityInput.value,
      trader_id: traderId,
    };
    if (PRICE_REQUIRED_TYPES.has(orderType)) {
      if (!priceInput.value) {
        feedback.textContent = "Price is required for this order type.";
        feedback.className = "feedback err";
        return;
      }
      payload.price = priceInput.value;
    }
    if (STOP_PRICE_REQUIRED_TYPES.has(orderType)) {
      if (!stopPriceInput.value) {
        feedback.textContent = "Stop/trigger price is required for this order type.";
        feedback.className = "feedback err";
        return;
      }
      payload.stop_price = stopPriceInput.value;
    }

    submitBtn.disabled = true;
    try {
      const res = await fetch("/order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        feedback.textContent = data.detail || "Order rejected.";
        feedback.className = "feedback err";
      } else {
        const fillCount = data.trades ? data.trades.length : 0;
        let msg = `Order accepted (${data.order_id.slice(0, 8)}…) — ${fillCount} fill${fillCount === 1 ? "" : "s"}.`;
        if (data.self_trade_prevented) {
          msg += " Self-trade prevented — skipped your own resting order(s) on the other side.";
        }
        feedback.textContent = msg;
        feedback.className = "feedback ok";
        orderForm.reset();
        traderIdInput.value = traderId;
        orderTypeSelect.value = orderType;
        updateFieldVisibility();
        refreshOpenOrders();
      }
    } catch (err) {
      feedback.textContent = "Could not reach the server.";
      feedback.className = "feedback err";
    } finally {
      submitBtn.disabled = false;
    }
  });

  // ---------------------------
  // Open orders panel
  // ---------------------------
  async function refreshOpenOrders() {
    const traderId = currentTraderId();
    if (!traderId) {
      openOrdersEl.innerHTML = `<div class="empty-hint">Enter a trader name to see your open orders.</div>`;
      return;
    }
    try {
      const res = await fetch(`/orders/${encodeURIComponent(traderId)}`);
      if (!res.ok) return;
      const data = await res.json();
      renderOpenOrders(data.orders || []);
    } catch {
      // silent - this is a background refresh, don't spam the feedback line
    }
  }

  function renderOpenOrders(orders) {
    if (!orders.length) {
      openOrdersEl.innerHTML = `<div class="empty-hint">No open orders.</div>`;
      return;
    }
    openOrdersEl.innerHTML = orders
      .map((o) => `
        <div class="open-order-row" data-order-id="${o.order_id}">
          <span class="oo-side ${o.side}">${o.side.toUpperCase()}</span>
          <span class="oo-meta">${o.symbol} · ${o.order_type} · ${o.remaining}${o.price ? " @ " + o.price : ""}</span>
          <button class="cancel-btn" type="button">Cancel</button>
        </div>
      `)
      .join("");
    openOrdersEl.querySelectorAll(".open-order-row").forEach((row) => {
      const orderId = row.dataset.orderId;
      row.querySelector(".cancel-btn").addEventListener("click", () => cancelOrder(orderId, row));
    });
  }

  async function cancelOrder(orderId, row) {
    const traderId = currentTraderId();
    const btn = row.querySelector(".cancel-btn");
    btn.disabled = true;
    btn.textContent = "…";
    try {
      const res = await fetch(`/order/${orderId}?trader_id=${encodeURIComponent(traderId)}`, { method: "DELETE" });
      if (res.ok) {
        row.remove();
        if (!openOrdersEl.children.length) {
          openOrdersEl.innerHTML = `<div class="empty-hint">No open orders.</div>`;
        }
      } else {
        const data = await res.json().catch(() => ({}));
        feedback.textContent = data.detail || "Could not cancel order.";
        feedback.className = "feedback err";
        btn.disabled = false;
        btn.textContent = "Cancel";
      }
    } catch {
      btn.disabled = false;
      btn.textContent = "Cancel";
    }
  }

  // ---------------------------
  // Rendering helpers
  // ---------------------------
  function renderBook(asks, bids) {
    bidsBody.innerHTML = bids.length
      ? bids.map(([price, qty]) => `<div class="book-row bid"><span class="price">${price}</span><span>${qty}</span></div>`).join("")
      : `<div class="book-empty">No bids</div>`;
    asksBody.innerHTML = asks.length
      ? asks.map(([price, qty]) => `<div class="book-row ask"><span class="price">${price}</span><span>${qty}</span></div>`).join("")
      : `<div class="book-empty">No asks</div>`;
  }

  function renderBbo(bid, ask) {
    bboBid.textContent = bid ?? "—";
    bboAsk.textContent = ask ?? "—";
    if (bid && ask) {
      const spread = (parseFloat(ask) - parseFloat(bid)).toFixed(8).replace(/0+$/, "").replace(/\.$/, "");
      bboSpread.textContent = spread;
    } else {
      bboSpread.textContent = "—";
    }
  }

  function prependTrade(trade) {
    if (seenTradeIds.has(trade.trade_id)) return;
    seenTradeIds.add(trade.trade_id);

    const emptyHint = tradeTape.querySelector(".empty-hint");
    if (emptyHint) emptyHint.remove();

    const row = document.createElement("div");
    row.className = "trade-row";
    const time = new Date(trade.timestamp).toLocaleTimeString();
    const sideClass = trade.aggressor_side === "buy" ? "side-buy" : "side-sell";
    row.innerHTML = `
      <span class="t-time">${time}</span>
      <span class="${sideClass}">${trade.aggressor_side.toUpperCase()}</span>
      <span>${trade.price}</span>
      <span>${trade.quantity}</span>
    `;
    tradeTape.prepend(row);
    while (tradeTape.children.length > 50) {
      tradeTape.removeChild(tradeTape.lastChild);
    }

    // A trade may have filled/consumed one of the current trader's own resting orders.
    refreshOpenOrders();
  }

  function resetPanels() {
    bidsBody.innerHTML = "";
    asksBody.innerHTML = "";
    renderBbo(null, null);
    tradeTape.innerHTML = `<div class="empty-hint">Trades will appear here as they execute.</div>`;
    seenTradeIds.clear();
  }

  // ---------------------------
  // WebSocket connection
  // ---------------------------
  function setConnStatus(state) {
    connStatus.className = `conn-status conn-${state}`;
    connStatus.innerHTML =
      state === "open"
        ? `<span class="dot"></span> live`
        : state === "closed"
        ? `<span class="dot"></span> disconnected — retrying…`
        : `<span class="dot"></span> connecting…`;
  }

  function subscribe(symbol) {
    ["bbo", "book", "trades"].forEach((feed) => {
      ws.send(JSON.stringify({ action: "subscribe", feed, symbol }));
    });
  }

  function unsubscribe(symbol) {
    ["bbo", "book", "trades"].forEach((feed) => {
      ws.send(JSON.stringify({ action: "unsubscribe", feed, symbol }));
    });
  }

  function connect() {
    setConnStatus("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      setConnStatus("open");
      subscribe(currentSymbol);
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (msg.type === "bbo" && msg.data.symbol === currentSymbol) {
        renderBbo(msg.data.bid, msg.data.ask);
      } else if (msg.type === "l2_update" && msg.data.symbol === currentSymbol) {
        renderBook(msg.data.asks, msg.data.bids);
      } else if (msg.type === "trade" && msg.data.symbol === currentSymbol) {
        prependTrade(msg.data);
      }
    };

    ws.onclose = () => {
      setConnStatus("closed");
      reconnectTimer = setTimeout(connect, 1500);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  symbolSelect.addEventListener("change", () => {
    const previous = currentSymbol;
    currentSymbol = symbolSelect.value;
    resetPanels();
    if (ws && ws.readyState === WebSocket.OPEN) {
      unsubscribe(previous);
      subscribe(currentSymbol);
    }
  });

  window.addEventListener("beforeunload", () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (openOrdersPoll) clearInterval(openOrdersPoll);
    if (ws) ws.close();
  });

  connect();
  refreshOpenOrders();
  openOrdersPoll = setInterval(refreshOpenOrders, 3000);
})();
