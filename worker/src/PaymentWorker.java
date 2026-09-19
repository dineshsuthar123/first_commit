import com.google.gson.*;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.sql.*;
import java.time.Duration;
import java.util.*;

/** Sample benchmark business logic. Controller cannot manufacture effects. */
public class PaymentWorker {
    static final Gson JSON = new Gson();
    static final BufferedReader INPUT = new BufferedReader(new InputStreamReader(System.in));
    static JsonObject delivery;
    static JsonObject op;
    static Map<String, Integer> occurrences = new HashMap<>();

    static void emit(JsonObject event) {
        event.addProperty("operationId", op.get("operationId").getAsString());
        event.addProperty("attempt", delivery.get("attempt").getAsInt());
        System.out.println(JSON.toJson(event));
        System.out.flush();
    }

    static void checkpoint(String name) throws Exception {
        JsonObject e = new JsonObject();
        e.addProperty("type", "checkpoint");
        e.addProperty("checkpoint", name);
        e.addProperty("occurrence", occurrences.merge(name, 1, Integer::sum));
        emit(e);
        String line = INPUT.readLine();
        if (line == null || !JsonParser.parseString(line).getAsJsonObject().get("decision").getAsString().equals("continue"))
            throw new IOException("controller disconnected or invalid decision");
    }

    static void persist(Connection db, String effect) throws SQLException {
        try (PreparedStatement st = db.prepareStatement("INSERT INTO payments(operation_id,order_id,amount_minor,currency,status,effect_id) VALUES(?,?,?,?,'paid',?) ON CONFLICT(operation_id) DO NOTHING")) {
            st.setString(1, op.get("operationId").getAsString());
            st.setString(2, op.get("orderId").getAsString());
            st.setLong(3, op.get("amountMinor").getAsLong());
            st.setString(4, op.get("currency").getAsString());
            st.setString(5, effect);
            st.executeUpdate(); // autocommit: durable before checkpoint
        }
    }

    static void handle(Connection db, String variant) throws Exception {
        checkpoint("before_local_read");
        boolean paid;
        try (PreparedStatement st = db.prepareStatement("SELECT status FROM payments WHERE operation_id=?")) {
            st.setString(1, op.get("operationId").getAsString());
            try (ResultSet rs = st.executeQuery()) { paid = rs.next() && rs.getString(1).equals("paid"); }
        }
        checkpoint("after_local_read");
        if (!paid) {
            if (variant.equals("mark_before")) {
                persist(db, null);
                checkpoint("after_local_commit");
            }
            checkpoint("before_external_call");
            JsonObject request = op.deepCopy();
            if (variant.equals("stable_key"))
                request.addProperty("idempotencyKey", "stateproof:payment:v1:" + op.get("operationId").getAsString());
            if (variant.equals("per_attempt_key"))
                request.addProperty("idempotencyKey", "stateproof:attempt:" + delivery.get("attemptId").getAsString());
            HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
            HttpResponse<String> response = client.send(HttpRequest.newBuilder(URI.create(System.getenv("PROVIDER_URL") + "/charge"))
                .timeout(Duration.ofSeconds(5)).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(JSON.toJson(request))).build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() / 100 != 2) throw new IOException("provider " + response.statusCode() + ": " + response.body());
            JsonObject result = JsonParser.parseString(response.body()).getAsJsonObject();
            JsonObject effect = new JsonObject();
            effect.addProperty("type", "provider_response");
            effect.add("effectId", result.get("effectId"));
            effect.add("deduplicated", result.get("deduplicated"));
            emit(effect);
            checkpoint("after_external_call");
            if (!variant.equals("mark_before")) {
                persist(db, result.get("effectId").getAsString());
                checkpoint("after_local_commit");
            }
        }
        checkpoint("before_ack");
        JsonObject done = new JsonObject(); done.addProperty("type", "ack"); emit(done);
    }

    public static void main(String[] args) throws Exception {
        delivery = JsonParser.parseString(INPUT.readLine()).getAsJsonObject();
        op = delivery.getAsJsonObject("operation");
        long amount = op.get("amountMinor").getAsLong();
        if (amount < 1 || amount > 100000000 || !Set.of("INR", "USD", "EUR").contains(op.get("currency").getAsString()))
            throw new IllegalArgumentException("invalid payment");
        String schema = System.getenv("APP_SCHEMA");
        if (!schema.matches("sp_[a-f0-9]{32}")) throw new IllegalArgumentException("invalid schema");
        try (Connection db = DriverManager.getConnection(System.getenv("JDBC_URL"), System.getenv("PGUSER"), System.getenv("PGPASSWORD"))) {
            db.setAutoCommit(true);
            try (Statement st = db.createStatement()) { st.execute("SET search_path TO " + schema); }
            handle(db, delivery.get("variant").getAsString());
        }
    }
}
