const STRIPE_CATALOG = {
  "tiers": {
    "mini": {
      "name": "SurePups Custom Mobility Cart \u2014 Mini Class (< 25 lbs)",
      "price_cents": 24500,
      "sku": "SP-CART-MINI",
      "stripe_product_id": "prod_VVYZOMmafYP9bY",
      "stripe_price_id": "price_1UUXSbBXOFxyF6Jv3rIIK8ia"
    },
    "standard": {
      "name": "SurePups Custom Mobility Cart \u2014 Standard Class (25\u201360 lbs)",
      "price_cents": 26500,
      "sku": "SP-CART-STD",
      "stripe_product_id": "prod_VVYZtRFb3912tF",
      "stripe_price_id": "price_1UUXSbBXOFxyF6JvAADmF3RQ"
    },
    "heavy": {
      "name": "SurePups Custom Mobility Cart \u2014 Heavy Duty Class (60\u2013110+ lbs)",
      "price_cents": 29500,
      "sku": "SP-CART-HD",
      "stripe_product_id": "prod_VVYZ4qeOko8YeM",
      "stripe_price_id": "price_1UUXScBXOFxyF6JvtJs2JA7o"
    }
  },
  "addons": {
    "stirrup": {
      "name": "Rear Limb Padded Stirrup Sling Kit",
      "price_cents": 2400,
      "sku": "SP-ADD-SLING",
      "stripe_product_id": "prod_VVYZ7MqOPtoN92",
      "stripe_price_id": "price_1UUXScBXOFxyF6JvfKBK5LbX"
    },
    "saddle": {
      "name": "Spare Washable Neoprene Pelvic Saddle",
      "price_cents": 3500,
      "sku": "SP-ADD-SADDLE",
      "stripe_product_id": "prod_VVYZf6Rs4dNli6",
      "stripe_price_id": "price_1UUXSdBXOFxyF6JvNi88GphR"
    },
    "rush": {
      "name": "Priority 48-Hour Rush Fabrication",
      "price_cents": 4500,
      "sku": "SP-ADD-RUSH",
      "stripe_product_id": "prod_VVYZtRj6ptAciC",
      "stripe_price_id": "price_1UUXSdBXOFxyF6Jvv2Y5hVzV"
    }
  }
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.hostname === "surepups.com") {
      url.hostname = "www.surepups.com";
      return Response.redirect(url.toString(), 301);
    }

    if (url.pathname === "/flutter_service_worker.js" || url.pathname === "/sw.js") {
      const selfUnregister = `
        self.addEventListener('install', () => self.skipWaiting());
        self.addEventListener('activate', () => {
          self.registration.unregister();
          caches.keys().then(keys => Promise.all(keys.map(k => caches.delete(k))));
        });
      `;
      return new Response(selfUnregister, {
        headers: {
          "Content-Type": "application/javascript",
          "Cache-Control": "no-store, no-cache, must-revalidate",
          "Clear-Site-Data": '"cache", "storage"'
        }
      });
    }

    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization"
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    if (url.pathname === "/api/v1/stripe-catalog") {
      return new Response(JSON.stringify(STRIPE_CATALOG), {
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }

    if (url.pathname === "/api/v1/checkout" && request.method === "POST") {
      try {
        const body = await request.json();
        const stripeKey = (env.STRIPE_SECRET_KEY || "").trim();
        if (!(stripeKey.startsWith("sk_") || stripeKey.startsWith("rk_"))) {
          return new Response(JSON.stringify({ ok: false, error: "Stripe key not configured on worker" }), {
            status: 500,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }

        const weight = parseFloat(body.weight || 48);
        let tierKey = "standard";
        if (weight < 25) tierKey = "mini";
        else if (weight > 60) tierKey = "heavy";

        const tierObj = STRIPE_CATALOG.tiers[tierKey];
        const params = new URLSearchParams();
        params.append("mode", "payment");
        params.append("success_url", `https://www.surepups.com/?checkout=success&order_ref=${encodeURIComponent(body.order_ref || "")}&session_id={CHECKOUT_SESSION_ID}`);
        params.append("cancel_url", "https://www.surepups.com/?checkout=cancelled#order-form");
        params.append("billing_address_collection", "required");
        params.append("shipping_address_collection[allowed_countries][0]", "US");
        params.append("shipping_address_collection[allowed_countries][1]", "CA");

        if (body.owner_email) {
          params.append("customer_email", body.owner_email);
        }

        let lineIdx = 0;
        params.append(`line_items[${lineIdx}][price]`, tierObj.stripe_price_id);
        params.append(`line_items[${lineIdx}][quantity]`, "1");
        lineIdx++;

        const selectedAddons = Array.isArray(body.addon_keys) ? body.addon_keys : [];
        for (const aKey of selectedAddons) {
          const addonObj = STRIPE_CATALOG.addons[aKey];
          if (addonObj && addonObj.stripe_price_id) {
            params.append(`line_items[${lineIdx}][price]`, addonObj.stripe_price_id);
            params.append(`line_items[${lineIdx}][quantity]`, "1");
            lineIdx++;
          }
        }

        params.append("metadata[order_ref]", String(body.order_ref || ""));
        params.append("metadata[dog_name]", String(body.dog_name || ""));
        params.append("metadata[dog_breed]", String(body.dog_breed || ""));
        params.append("metadata[owner_name]", String(body.owner_name || ""));
        params.append("metadata[weight_lbs]", String(body.weight || ""));
        params.append("metadata[flank_height_in]", String(body.flank_height || ""));
        params.append("metadata[body_length_in]", String(body.body_length || ""));
        params.append("metadata[hip_width_in]", String(body.hip_width || ""));
        params.append("metadata[tpu_color]", String(body.tpu_color || "Cyan Blue"));

        const sResp = await fetch("https://api.stripe.com/v1/checkout/sessions", {
          method: "POST",
          headers: {
            "Authorization": `Bearer ${stripeKey}`,
            "Content-Type": "application/x-www-form-urlencoded"
          },
          body: params.toString()
        });
        const sData = await sResp.json();
        if (sData.url) {
          return new Response(JSON.stringify({
            ok: true,
            checkout_url: sData.url,
            session_id: sData.id
          }), {
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        } else {
          return new Response(JSON.stringify({
            ok: false,
            error: (sData.error && sData.error.message) ? sData.error.message : "Stripe session error"
          }), {
            status: 400,
            headers: { ...corsHeaders, "Content-Type": "application/json" }
          });
        }
      } catch (err) {
        return new Response(JSON.stringify({ ok: false, error: err.message }), {
          status: 500,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }
    }

    if (env && env.ASSETS) {
      const assetResp = await env.ASSETS.fetch(request);
      if (url.pathname === "/" || url.pathname === "/index.html") {
        const newHeaders = new Headers(assetResp.headers);
        newHeaders.set("Cache-Control", "no-store, no-cache, must-revalidate");
        return new Response(assetResp.body, {
          status: assetResp.status,
          headers: newHeaders
        });
      }
      return assetResp;
    }

    return new Response("SurePups Mobility Online", { status: 200 });
  }
};
