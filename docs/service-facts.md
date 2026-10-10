# Service facts (OTel Astronomy Shop 3.1.0)

Read from the source, so the agents can explain *why*, not just *what*. Cite them as `service-facts`.

**Checkout `PlaceOrder`, in order** ([main.go](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/checkout/main.go)):
1. Prepare: cart, product catalog, currency, shipping quote (shipping → quote). A failure here means no charge.
2. Charge the card via payment ([L361](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/checkout/main.go#L361)).
3. Ship via shipping `/ship-order` ([L374](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/checkout/main.go#L374)). A failure returns "shipping error" **after the charge, with no refund**.
4. Empty the cart. The error is ignored ([L381](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/checkout/main.go#L381)).
5. Order confirmation email. A failure is only logged as a warning.
6. Publish the order to Kafka. It waits for Kafka until the request's deadline, then logs and drops the event ([L663](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/checkout/main.go#L663)).

**Frontend**
- Prices: USD skips the currency service; any other currency calls `currency.convert` once per product ([ProductCatalog.service.ts](https://github.com/open-telemetry/opentelemetry-demo/blob/3.1.0/src/frontend/services/ProductCatalog.service.ts)).
- `/api/products` → product-catalog (+ currency if not USD)
- `/api/shipping` → shipping `/get-quote` → quote, + currency
- `/api/recommendations` → recommendation → product-catalog
- `/api/cart` → cart → valkey-cart
- `/api/data` → ad
- `/api/checkout` → checkout

**Data**
- No volumes: valkey-cart (carts, memory only), kafka (the orders queue), astronomy-db (the catalog, plus accounting's orders).
- accounting consumes orders from Kafka and writes them to astronomy-db. fraud-detection consumes the same topic.

**Topology**
- Every service runs 1 replica. All app services listen on 8080; flagd on 8013, with 13 dependents in the map.
- `chaos-worker` ("blast"): the backends; node faults target it.
- `chaos-worker2` ("steady"): frontend, frontend-proxy, flagd, load generator, monitoring.
- Customer-facing in the bank's rules: frontend, frontend-proxy, checkout.
