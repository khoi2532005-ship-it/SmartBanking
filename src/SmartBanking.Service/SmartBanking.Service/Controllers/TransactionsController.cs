using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Mvc;
using SmartBanking.Database.Service;

namespace SmartBanking.Service.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class TransactionsController : ControllerBase
    {
        private readonly IDatabaseClient _db;

        public TransactionsController(IDatabaseClient db)
        {
            _db = db;
        }

        [HttpGet]
        public async Task<IActionResult> Get([FromQuery] string? account_id, [FromQuery] string? customer_id)
        {
            var filters = new Dictionary<string, string>();
            if (!string.IsNullOrEmpty(account_id)) filters["account_id"] = account_id;
            if (!string.IsNullOrEmpty(customer_id)) filters["customer_id"] = customer_id;

            var tx = await _db.GetTransactionsAsync(filters);
            return Ok(tx);
        }

        [HttpGet("{id}")]
        public async Task<IActionResult> GetById(int id)
        {
            var tx = await _db.GetTransactionAsync(id);
            if (tx == null) return NotFound();
            return Ok(tx);
        }
    }
}
