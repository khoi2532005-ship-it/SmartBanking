using System;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace SmartBanking.Database.Service
{
    public static class DatabaseClientExtensions
    {
        public static IServiceCollection AddDatabaseClient(this IServiceCollection services, IConfiguration config)
        {
            var baseUrl = config.GetValue<string>("DatabaseService:BaseUrl") ?? "http://localhost:5012";
            services.AddHttpClient<IDatabaseClient, DatabaseClient>(client => client.BaseAddress = new Uri(baseUrl));
            return services;
        }
    }
}
